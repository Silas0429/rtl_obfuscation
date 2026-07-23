# T042：SymbolGraph genvar source identity 与受控 generate provenance

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R2-C
- 前置任务：T041 `ACCEPTED`，交付提交 `89b8a55`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 2、3、5、6、7 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- 验收类型：SymbolGraph/range
- Formal verification：`N/A`，本任务只扩展 SymbolGraph，不产生 rewritten RTL

## 1. 当前项目状态与本任务位置

统一替代架构当前已经具备：

```text
T039 SourceSet
  -> T040 SourceCatalog / ModuleOwner
  -> T041 signals-only SymbolGraph
  -> T042 genvars + generate_syntax provenance
  -> 后续 parameter/localparam + ABI classification
  -> RewritePolicy / mapping vNext / rewrite
```

T038 的 `6835`/`6882` 冲突继续作为历史证据，不恢复其 legacy inventory、mapping v4 或 RISC
Formal。T042 只吸收其中已经被 compact SystemVerilog 输入证明的语义事实：source `GenvarSymbol`
可能对应多个 elaborated iteration `ParameterSymbol`；generate header/body 的物理 token 需要在受限
`LoopGenerateSyntax` 上恢复，并且必须按 source declaration 和 module owner 归一化。

选择 `genvars` 先于 `parameters` 的原因：genvar 是纯 module-internal、非 ABI 对象，可以先独立验证
syntax provenance；module parameter/localparam 还涉及 named override、dimension、generate condition、
`module_abi/top_boundary`，必须留给单独的 R2-D 合同，不能在 T042 顺手加入。

## 2. 单一目标

扩展 `rtl_obfuscator/symbol_graph.py`：在 T041 signals graph 之外增加 module-owned source
`genvars`，将 inline genvar、独立声明且被多个 generate-for 复用的 genvar，以及 elaborated iteration
parameters 归一化为唯一 SourceSymbol，并为全部受支持的物理引用记录 `generate_syntax` provenance。

本任务必须保持：

1. 输入仍是一个已经成功建立的 `SourceCatalog`；
2. 不重新编译、不读取 top overlay semantic tree、不调用 legacy inventory/rewrite；
3. T041 signals 的 source identity、错误码、6/6/12/18 audit 和 15 个测试不回退；
4. 一个 source genvar 只产生一个 SourceSymbol，elaborated iteration ParameterSymbol 不产生独立 entry；
5. syntax occurrence 只能来自 genvar declaring module 的精确 `LoopGenerateSyntax`，禁止全文件文本搜索；
6. 任一 macro、nested ownership 或 source range 无法证明时 whole-graph fail-closed，不输出部分 graph。

## 3. 冻结输入（由主 Agent 建立并预检）

### 3.1 正例

```text
tests/fixtures/refactor_symbol_graph_genvars/
  design.f
  closure.f
  single.f
  single.sv
  rtl/design.sv
  rtl/unreachable.sv
```

语义：

- `genvar_reuse` 独立声明 `j`，在两个同级 generate-for 中复用；
- 每个 `j` loop 有 initializer、condition、`j = j + 1` 两个 iteration token 和一个 body
  dimension token，合计 `j` declaration 1 + references 10；
- `genvar_shadow` 同时有 module parameter `k` 和 inline genvar `k`；只有 inline genvar 进入 T042，
  references 为 condition、iteration、body dimension 共 3；
- `genvar_unreachable` 另有同名 inline genvar `k`，references 为 3，用于验证同名 owner 分离和
  filelist top 不裁剪 SourceSet；
- `genvar_single` 有 inline genvar `only`，references 为 3，用于 single-file/filelist 对等；
- 正例没有 nested generate-for、macro genvar、inactive generate 或 UninstantiatedDefSymbol。

### 3.2 负例

```text
tests/fixtures/refactor_symbol_graph_genvars_invalid/
  macro.f
  macro_reference.f
  nested.f
  rtl/macro.sv
  rtl/macro_reference.sv
  rtl/nested.sv
```

- `macro.sv`：genvar declaration 来自 function-like macro；
- `macro_reference.sv`：genvar declaration 为直接物理 token，但 condition reference 来自 macro；
- `nested.sv`：两个合法 nested inline generate-for 使用同名 `i`，T042 不尝试猜测内外 lexical owner。

### 3.3 冻结 hash

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `refactor_symbol_graph_genvars/design.f` | 33 | `c51da7a451f842d2847d28450d45ca77666ec98bcdba5a81d28def55c8265e68` |
| `refactor_symbol_graph_genvars/closure.f` | 14 | `d13227ab5c33ad28d1f6e9769177dfcf2fe6cd7b74ca4f64dcdddd36bdf3dfcb` |
| `refactor_symbol_graph_genvars/rtl/design.sv` | 511 | `7bf8daf3c91a73b386bd92eb1ce9c273c2e03a53f5542689295860f573e6217c` |
| `refactor_symbol_graph_genvars/rtl/unreachable.sv` | 130 | `fa03c98c1dd15ae22d0bd9ba9838aca584b6a248d1eef21fd28bc7f6b3c58687` |
| `refactor_symbol_graph_genvars/single.f` | 10 | `c212b204450e94afc4afc2c3a4f42c47a2586c7d651203a8b562a45591602461` |
| `refactor_symbol_graph_genvars/single.sv` | 133 | `c2f14679011814fc3d0fc4b9e0e07a458f3017637f9ceef927d4ac097542b5d9` |
| `refactor_symbol_graph_genvars_invalid/macro.f` | 13 | `e80759aef554c40fe00a9b5706a191d075b00999ebf75688080b9832f12c97d6` |
| `refactor_symbol_graph_genvars_invalid/macro_reference.f` | 23 | `b3738dfc81f16b979969cb837cfb97eb75c20ab7cdc555099838ac2c8eb34daa` |
| `refactor_symbol_graph_genvars_invalid/nested.f` | 14 | `e66de0cdce1d06172d7acd6c509aa24ca90ea9ed15b6c46b84b118d81386a14a` |
| `refactor_symbol_graph_genvars_invalid/rtl/macro.sv` | 181 | `039aa722eb1068d000f08e8fa524ddecfa8968beac0ef9ffaef543be01bed955` |
| `refactor_symbol_graph_genvars_invalid/rtl/macro_reference.sv` | 203 | `64cb9cabe9428dd88e031320fe026e65e508b66274c2614b823a4f30112c3098` |
| `refactor_symbol_graph_genvars_invalid/rtl/nested.sv` | 195 | `79b017d27c1c70e5247eabee144c36f5b3410f6d36109c9461bdd4c2ca17e655` |

这些 fixture 是主 Agent冻结输入。子 Agent不得修改；hash 不一致必须停止，不能更新 oracle。

### 3.4 主 Agent PySlang 预检

全部正/负 filelist 的 `SourceCatalog` 均为 `parse_errors=0, semantic_errors=0`。完整 filelist
semantic tree 实测有 source genvars `j/k/k` 和 7 个 body parameters；macro declaration location
`isMacroLoc=True`；macro reference 的对应 syntax identifier location `isMacroLoc=True`；nested fixture
有两个 source declaration ranges（semantic elaboration 可重复 node），且没有 UninstantiatedDefSymbol。
按 T041 source identity规则预检得到 full/closure/single分别为4/3/1个直接物理signal declarations，
与第6节whole-graph audit一致。

该预检只证明合同输入可构造，不授权调用 legacy collector，也不作为子 Agent 验收结果。

## 4. 公开 API 与 report 合同

T042 不新增公开类或函数；继续使用 T041：

```python
build_symbol_graph(source_catalog: SourceCatalog) -> SymbolGraph
```

`SourceSymbol` schema 不变。新增 genvar 记录固定为：

```text
category: genvars
impact: local
abi: internal
support: eligible
reason: null
semantic_owner: 与 owner_module 相同的 T040 ModuleOwner.owner_id
symbol_id: symbol:genvars:<file>:<start>:<end>
```

`SymbolGraph.to_report()["categories"]` 从 T042 起定义为 graph 中实际出现 category 的 canonical
顺序，当前顺序为 `signals`、`genvars`。因此：

- T041 无 genvar fixture 仍输出 `["signals"]`；
- T042 正例输出 `["signals", "genvars"]`；
- 不允许把固定 fixture 名称或数量写入 report 分支。

其他 schema 字段不变，不增加 mapping、policy、preserved 或 unsupported 数组。

## 5. source identity 与 owner 规则

### 5.1 genvar candidate

只收集满足以下全部条件的 semantic source object：

- kind 为 `SymbolKind.Genvar`；
- 名称非空且不以 `$` 开头；
- declaringDefinition 为 SourceCatalog 中 module definition；
- declaration 是 SourceSet 内直接物理 identifier token，且不是 macro location；
- declaration 能通过 T040 module declaration range 唯一映射到 ModuleOwner。

同一 physical declaration 因 elaboration 重复出现时按 `(file,start,end)` 归一化。kind 为
`Parameter` 的 iteration/body parameter 只作为 semantic owner evidence，不得成为 `parameters`
或 `genvars` SourceSymbol。

### 5.2 受控 loop 关联

只能遍历 candidate genvar 的 `declaringDefinition.syntax` 中的 `LoopGenerateSyntax`：

- inline genvar 由 loop declaration identifier 的物理 location 与 source genvar declaration 对应；
- 独立 module-scope genvar 允许被同一 module 的多个同级 loop 复用；loop identifier 必须在该 module
  内只有一个 source genvar candidate，并存在同名 `isLocalParam/isBodyParam` iteration semantic evidence；
- 不得按 project/file 全局同名匹配，不得使用正则或 `str.find`；
- loop 内出现 nested `LoopGenerateSyntax` 时 T042 整图返回
  `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`，不收集部分 occurrence；
- 没有任何 loop 的直接物理 genvar declaration允许以 `occurrences=()` 存在；但一旦发现同名 loop
  而无法唯一关联，必须 fail-closed。

### 5.3 candidate-scoped fail-closed

T041 的 no-token 检查必须限定到当前 graph candidate：

- 绑定 signals 的引用继续严格执行 T041 direct-token 规则；
- 绑定 source genvar或其 iteration parameters 的引用按本任务受控 syntax规则处理；
- 尚未进入 graph 的 ports、module parameters、localparams等对象不会仅因 generated semantic node
  `syntax is None` 使 signals/genvars graph失败，也不得被误收集；
- 这不是 parameter 支持或 fallback，只是把 T041 fail-closed 恢复到 candidate 边界。

## 6. occurrences、provenance 与审计

- declaration 不进入 occurrences；
- genvar occurrence 唯一允许的 provenance 为 `generate_syntax`；
- occurrence 来自已关联 LoopGenerateSyntax 中属于该 genvar的 initializer/condition/iteration/body
  identifier token；inline declaration token只作为 declaration，不重复为 occurrence；
- 每个 token 先拒绝 macro location，再校验 source file、byte range 和 bytes；
- repeated elaboration、iteration count和多个 semantic node不得复制同一 physical occurrence；
- occurrences、symbols和全局 range继续使用 T041排序、唯一、非重叠审计。

冻结正例结果：

| input | genvar symbols | genvar references | genvar total ranges | whole graph audit |
| --- | ---: | ---: | ---: | --- |
| `design.f`，有或无 top | 3 (`j`,`k`,`k`) | 16 (`10+3+3`) | 19 | `7 symbols / 7 declarations / 16 occurrences / 23 total_ranges` |
| `closure.f + genvar_top` | 2 (`j`,`k`) | 13 (`10+3`) | 15 | `5 / 5 / 13 / 18` |
| `project-root + genvar_top` | 2 (`j`,`k`) | 13 | 15 | normalized 后与 closure filelist 相同 |
| `single.sv` 或 `single.f` | 1 (`only`) | 3 | 4 | `2 / 2 / 3 / 5` |

whole graph 中其余 symbols 是 T041 signals (`lane_first/lane_second/lane_shadow/lane_hidden/lane_only`)；
其 declaration 因 elaboration重复仍只出现一次。

## 7. 稳定失败矩阵

T041 已验收的错误码和六项负例继续由 `tests.test_symbol_graph_signals` 覆盖。T042新增并冻结：

| input | SourceCatalog 前置条件 | expected code |
| --- | --- | --- |
| macro-generated genvar declaration | 0/0 diagnostics | `SYMBOL_GRAPH_UNSUPPORTED_SOURCE` |
| physical declaration + macro-generated genvar reference | 0/0 diagnostics | `SYMBOL_GRAPH_UNSUPPORTED_SOURCE` |
| valid nested generate-for with same-name inner/outer genvar | 0/0 diagnostics, no UninstantiatedDefSymbol | `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE` |

异常仍使用 T041 `SymbolGraphError`，字符串以 `"<code>: "` 开头，并保存首个稳定 file/start（若可用）。
失败不返回部分 graph。T042不增加新错误码。

## 8. 目标测试

新增 `tests/test_symbol_graph_genvars.py`，使用公开 SourceSet adapter、`build_source_catalog()` 和
`build_symbol_graph()`，恰好覆盖以下 13 项可观察行为：

1. `design.f` 无 top 产生 3 个 genvar symbols、16 references和第 6 节完整 audit；
2. `design.f + genvar_top` 与无 top symbol payload相同并保留 closure 外 genvar `k`；
3. project-root 与 `closure.f + genvar_top` normalized report除 origin外相同；
4. single-file `single.sv` 与 `single.f` normalized report除 origin外相同；
5. 独立 `j` 在两个同级 loop 中仍为一个 SourceSymbol且有 10 个 references；
6. inline genvar `k` 与同 module parameter `k` 分离，只有 genvar进入 T042；
7. `genvar_shadow` 和 `genvar_unreachable` 的同名 genvar `k` 按 declaration/owner分离；
8. 全部 genvar bytes、`generate_syntax` provenance、排序、去重、非重叠和三个 audit oracle正确；
9. categories canonical、schema不变且连续 canonical JSON byte-identical；
10. monkeypatch T040 compile入口及 legacy genvar inventory/range helper为立即失败，graph仍成功；
11. macro genvar declaration返回 `SYMBOL_GRAPH_UNSUPPORTED_SOURCE`；
12. macro genvar reference返回 `SYMBOL_GRAPH_UNSUPPORTED_SOURCE`；
13. nested同名 genvar返回 `SYMBOL_GRAPH_UNSUPPORTED_REFERENCE`，不返回不完整 graph。

测试不得调用产品私有 SymbolGraph helper制造结果；不得从其他 compilation拼接 semantic node；不得
修改冻结 fixture。T041的 15 个测试与本任务13个测试在同一验收命令中运行，共至少28 tests。

## 9. 允许修改的文件

- `rtl_obfuscator/symbol_graph.py`；
- `tests/test_symbol_graph_genvars.py`；
- `docs/tasks/T042_symbol_graph_genvars.md`，仅状态和执行记录。

第 3 节 fixtures、T041 tests/task、SourceSet、SourceCatalog、legacy inventory/rewrite、README、
renaming table和其他规划文档均为只读。若实现确实需要修改允许列表外文件，记录具体原因并停止；
不得自行扩大合同。

## 10. 明确不包含

- 不增加 `parameters`、localparam、type parameter或任何其他 category；
- 不实现 parameter dimension/generate condition/named override；
- 不实现 module ABI、top boundary、preserved/unsupported逐 symbol schema或 RewritePolicy；
- 不支持 nested generate-for、macro genvar、inactive generate或外部 hierarchical genvar；
- 不调用或复制 legacy `_collect_genvars`、`_genvar_reference_tokens`；
- 不新增 lexical全文件扫描、第二次 compilation、缓存、CLI、mapping、rewrite或Formal；
- 不清理旧测试/脚本，不运行RISC或历史 acceptance driver。

## 11. 子 Agent 强制执行规范

1. 完整阅读 `AGENTS.md`、本任务、`docs/refactor_subagent_protocol.md` 和重构计划第2/3/5/6/7节；
2. 确认 `89b8a55` 是 HEAD祖先、T042合同与冻结 fixture已经由主 Agent提交、工作区干净，且本任务
   是唯一 `READY`任务；
3. 校验第3.3节全部 hash和第3.4节0/0诊断；任一不符立即停止，不得修改 fixture/oracle；
4. 将状态改为 `IN_PROGRESS`，记录 starting HEAD、工作区和 baseline；
5. baseline只运行第12节 unittest命令，预期仅因 `tests.test_symbol_graph_genvars`尚不存在而失败；
6. 先创建13项黑盒测试，再按 source identity、candidate-scoped dispatch、loop association、range audit
   顺序实现；一次完成后再申请 review，不分批请求主 Agent补合同；
7. 允许用不写仓库的PySlang只读输出诊断；若实际 API与第3.4/5节预检不同，记录最小输出并停止；
8. 普通测试失败属于任务内实现，不是暂停理由；只有 API不一致、fixture hash变化、需要允许文件外修改
   或无法唯一证明 owner/range时才停止；
9. 完成后只运行第12节四条命令，填写真实测试数/退出码/边界并设 `READY_FOR_REVIEW`；
10. 不得设置 `ACCEPTED`、执行 git add/commit/push、创建 T043或写主 Agent验收记录。

## 12. 唯一验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_symbol_graph_signals tests.test_symbol_graph_genvars -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/symbol_graph.py tests/test_symbol_graph_genvars.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T042_symbol_graph_genvars.md
```

不运行 blanket discovery、legacy genvar tests、HDL compile、gate、decrypt、Yosys、RISC-V-Vector或
历史 acceptance脚本。Formal为 `N/A: no rewritten RTL is produced`。主 Agent验收只审查本合同
13项行为并独立复跑以上四条命令，不增加隐藏 probe或新 oracle。

## 13. 子 Agent执行记录

```text
status: NOT_STARTED
starting_head:
fixture_hash_check:
catalog_preflight:
baseline_command:
baseline_result:
changed_files:
commands:
results:
schema_or_behavior:
deviations_or_blockers:
boundaries:
cleanup_candidates: none in T042
formal_verification: N/A - no rewritten RTL is produced
review_request:
```

## 14. READY_FOR_REVIEW 条件

- 第8节13项行为全部覆盖，T041+T042至少28 tests通过；
- 第12节四条命令全部退出0；
- diff只包含第9节允许文件，冻结 fixture hash不变；
- genvar declaration/owner/occurrences/provenance完整，三个固定 audit正确；
- repeated/inline/same-name/closure/三入口行为符合合同；
- 三项新增负例按第7节错误码whole-graph fail-closed；
- 没有第二次compile、legacy collector、全文件文本扫描、伪semantic root或fixture特判；
- Formal准确记录为 `N/A: no rewritten RTL is produced`；
- 状态严格为 `READY_FOR_REVIEW`。

## 15. 主 Agent验收边界

主 Agent只执行：

1. 审查子 Agent记录的 `starting_head -> working tree` diff、允许文件和冻结 fixture hash；
2. 确认13项测试由公开API和真实SourceCatalog触发；
3. 审查 source genvar、iteration parameter、LoopGenerateSyntax之间的owner证明，不接受同名全局匹配；
4. 在状态仍为 `READY_FOR_REVIEW` 时独立运行第12节四条命令；
5. 全部通过后写验收记录并设置 `ACCEPTED`。

任何退回必须引用本合同具体条款或第8节测试。验收时新想到但未冻结的 genvar形状记录为后续任务，
不能新增为T042阻塞条件。

## 16. 主 Agent合同冻结记录（2026-07-23）

```text
status: READY
baseline_commit: 89b8a55
decision: implement genvars before parameters so T042 remains internal/non-ABI and R2-D owns parameter ABI complexity
frozen_inputs: 12 files, hashes and byte sizes recorded in section 3.3
preflight: all SourceCatalog inputs are 0/0; source genvar, body parameter, macro location and nested-loop shapes were verified with project PySlang
positive_oracles: full 3/16/19 and graph 7/7/16/23; closure 2/13/15 and graph 5/5/13/18; single 1/3/4 and graph 2/2/3/5
negative_matrix: macro declaration, macro reference, valid nested same-name loops
acceptance: exactly four commands; T041 regression plus 13 T042 tests; no Formal or hidden probes
formal_verification: N/A - no rewritten RTL is produced
```
