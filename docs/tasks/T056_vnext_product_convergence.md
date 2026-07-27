# T056：vNext 类别闭环与产品入口收口

- 状态：ACCEPTED
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R5-A
- 前置任务：T055 `ACCEPTED`，交付提交 `ed71ad1`
- 设计基线：`11b76c7cd1a9f433584860e27d664a0158f17bc4`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 1–8 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- Formal 依据：`docs/formal_verification.md`
- 验收类型：legacy cleanup + replacement coverage；本任务通过最终产品 CLI 产生 rewritten RTL

## 1. 审计结论与任务缘由

T052–T055 已证明 single-file、filelist、project-root 三种输入可以共用 vNext orchestration、
gate、restore、metrics 和 rate 流水线，但开始 R5 清理前的主 Agent 审计发现：

1. `docs/systemverilog_renaming_table.md` 和现有 canonical registry 定义 19 个在范围内的 category；
2. 当前 vNext `SymbolGraph` / `RewritePolicy` 只实现 `signals`、`parameters`、`genvars`；
3. 旧 `inventory.py` / legacy CLI 仍承载其余 16 类；
4. 直接删除 legacy 会静默丢失已交付的 SystemVerilog 语义能力；
5. 现有 vNext 模块组合回归在 T055 后还有一个 stale project-root 负例，证明逐任务孤立验收不足以
   作为 cleanup replacement coverage。

因此 T056 不允许先删后补，也不允许把 19 类缩减为 3 类并称为 breaking change。T056 必须先在
唯一 `SourceCatalog -> SymbolGraph -> RewritePolicy -> MappingVNext` 路径中完成 19 类闭环，
再移除旧产品入口和旧 oracle 测试。

T054 的历史插入不再改写任务历史：实际 T054 是持久化 restore/decrypt 前置任务，实际 T055 对应
原计划的 project-root adapter；原计划的 legacy cleanup 与发布验收由 T056、T057 两张任务完成。
本任务不得创建第三张收口任务。

## 2. 单一目标

将 19 个已授权 SystemVerilog category 全部迁移到唯一 vNext SymbolGraph，并让
`encrypt-vnext` / `decrypt-vnext` 成为唯一用户-facing 加密与恢复入口；删除旧产品 CLI 分派和
只冻结 v1/v2/v3/v4、旧 profile、旧固定数量的非 RISC 测试，同时保持有效的语义、gate、
restore、rate、metrics、事务发布和 compact Formal 覆盖。

任务完成后：

- 产品加密/恢复不调用 `inventory.py`、legacy `project.py` analysis 或旧 mapping validator；
- 三种输入只通过 `SourceSet` 进入同一个 vNext 引擎；
- 19 类都由同一个 SymbolGraph owner/range/provenance 模型表达；
- 旧 mapping v1/v2/v3/v4 不进入主 CLI，也不提供离线兼容工具；
- T057 只剩 RISC-V-Vector 专项 alignment、专项 Formal 和最终发布冻结，不再补普通 category。

## 3. 最终产品 CLI

### 3.1 保留入口

```text
encrypt-vnext
decrypt-vnext
```

`encrypt-vnext` 继续支持且只支持三选一：

```text
--input <file.sv> --source-root <dir>
--filelist <design.f> --source-root <dir>
--project-root <dir> --top <module>
```

`decrypt-vnext` 继续只消费 T053–T056 portable orchestration report、actual gate 和原 source root。
现有 output overlap、existing target、atomic publish、tamper/hash/range/manifest 和无 traceback
错误语义保持不变。

### 3.2 删除入口

以下 operation 必须从 parser、dispatch、README 当前工作流和 `rewrite.py` 实现中删除：

```text
encrypt
decrypt
encrypt-project
decrypt-project
inspect-project
formal-view
formal-align
```

调用这些 operation 必须由 argparse 非零拒绝，不得 fallback 到 vNext 或继续读取旧 mapping。

T056 不为 `formal-view` / `formal-align` 保留隐藏 parser alias；T057 从 residual source
重新建立无固定数量的通用 alignment 和场景级 RISC oracle。导入或运行 `encrypt-vnext` /
`decrypt-vnext` 时不得加载 `inventory`、legacy `project`、`formal_view` 或
`category_profile`。

### 3.3 不提供旧 mapping 兼容

- 不新增 v1/v2/v3/v4 loader、converter、compatibility alias 或隐藏 operation；
- `decrypt-vnext` 读取旧 mapping 必须以既有稳定 report-invalid 类错误 fail-closed；
- 历史命令和数量只保留在已验收任务文档及 Git 历史中。

## 4. 唯一 category registry

新增 product-only registry，canonical 顺序固定为：

```text
signals
parameters
enum_values
genvars
functions
tasks
arguments
instances
generate_blocks
typedefs
struct_types
struct_fields
union_fields
modules
ports
interfaces
interface_instances
interface_ports
modports
```

默认选择和 `all` 都只展开前 13 个非显式 ABI category。alias 固定为：

```text
struct    -> struct_types, struct_fields
interface -> interfaces, interface_instances, interface_ports, modports
```

重复、乱序输入必须按 canonical 顺序去重；unknown、空字符串和非字符串必须 fail-closed。
新 registry 不得包含 single/filelist/project-root profile 分支，不得导入 legacy
`category_profile.py`。

允许成为 `module_abi` 的 category 固定为：

```text
parameters
typedefs
struct_types
struct_fields
union_fields
modules
ports
interfaces
interface_instances
interface_ports
modports
```

`--abi-category` 必须同时满足：

1. category 在上述集合中；
2. category 同时出现在 normalized `--category` 中；
3. SourceSet 提供合法 top；
4. SymbolGraph 已证明对象位于 selected-top closed closure；
5. selected top 自身 boundary 继续保持。

`signals`、`enum_values`、`genvars`、`functions`、`tasks`、`arguments`、`instances`、
`generate_blocks` 不接受 ABI opt-in。不得用输入模式决定 category collector。

## 5. SymbolGraph 迁移设计

### 5.1 统一记录

19 类都必须生成现有 `SourceSymbol`，保持 report schema：

```text
symbol_id
category
name
declaration
owner_module
semantic_owner
occurrences[]
occurrence_provenance
impact
abi
support
reason
```

不得新增第二种 entry 类型、legacy inventory projection 或按模式选择 collector。稳定
`symbol_id` 由 canonical category 和声明物理位置构成即可；`semantic_owner` 作为独立字段必须
来自 SourceCatalog registry 并通过 mapping 校验。两者共同证明 identity，但不得为了把 owner
再次编码进 `symbol_id` 而改变已经冻结的 vNext ID 形状。`symbol_id` 不得包含随机名、fixture 名
或运行时 object id。

### 5.2 owner 与 range

- module 内对象归属精确 module owner；
- function/task argument 和 function return variable 必须绑定其 subroutine owner，不能并入同名
  module signal；
- compilation-unit/shared aggregate type 使用稳定 `$unit`/声明 owner，不得按拼写合并；
- instance type、named connection、named parameter override、interface member/modport 和 aggregate
  member必须绑定声明对象；
- generate block、genvar 和 elaborated iteration parameter 必须保持不同 source owner；
- 每个 declaration/reference range 必须校验 source bytes；
- 一个 physical range 只能属于一个归一化后的 source symbol；不同 symbol 的精确重复、部分重叠
  和多 owner 必须 fail-closed；PySlang 对同一 category/name/owner/range 的重复 elaboration 暴露
  可以幂等归一，不要求依赖不稳定的运行时 object identity；
- lexical/syntax fallback 只有同时具备限定语法上下文、semantic owner 和 source-byte 证据时才可用。

### 5.3 ABI 与 top boundary

- 无 top：`internal` 可改写，所有 `module_abi` / `top_boundary` 保留；
- 有 top：只有显式 `--abi-category` 且 closure 内完整绑定的 `module_abi` 可改写；
- selected top module、ports、parameters 和外部 interface/type boundary 始终保留；
- module 内声明且全部消费者位于同一 module 的 typedef/struct/union type 与 field 属于
  `internal`；compilation-unit/shared 或跨 module 消费的 type/field 才属于 `module_abi`；
- filelist 继续覆盖全部列出的 module 的非 ABI 对象；top 只增加 ABI overlay；
- project-root 只覆盖 top closure；
- external hierarchical reference、未解析 owner、跨 SourceSet 消费者或不完整 interface/type binding
  必须 preserved/unsupported 或 stable fail-closed，不能按文本猜测。

## 6. SourceSet 与 discovery 隔离

新增无 inventory 依赖的 discovery 模块，并将 SourceSet 所需的以下能力从 legacy `project.py`
机械迁移过去：

```text
ProjectAnalysisError
SourceSetDiscovery
_discover_files
_discover_sourceset
```

`source_set.py` 只能导入新 discovery 模块。legacy `project.py` 可为 T057 暂时 re-export 这些名字，
但 product import graph 不得再经过 `project.py -> inventory.py`。

不得改变：

- explicit filelist 顺序；
- include dirs、defines 和 compilation-unit 语义；
- project-root top closure 与 compile order；
- `.svh` 只作为 physical include、不作为独立 source unit；
- single/filelist/project-root 的 portable SourceSet report。

## 7. 固定输入与机器可读输出

### 7.1 只读输入

不得修改任何 fixture 或 RTL sample。主要 replacement fixture：

```text
tests/fixtures/t033_impact_category/
tests/fixtures/t034_profile_scope/
tests/fixtures/t016_module_port/
tests/fixtures/t017_interface/
tests/fixtures/t018_interface_member/
tests/fixtures/t038_risc_v_parameter_genvar/
tests/fixtures/refactor_symbol_graph_signals/
tests/fixtures/refactor_symbol_graph_genvars/
tests/fixtures/refactor_symbol_graph_parameters/
rtl_samples/11_supported_obfuscation.sv
rtl_samples/example_fifo/
```

`tests/fixtures/t033_impact_category` 是 19 类 compact closure 主 oracle；测试可在临时目录创建
closure filelist、gate、negative gate、report 和 restore，不得把生成物写入仓库。

### 7.2 输出 schema

保持以下既有 format/schema，不新增 mapping version：

```text
rtl-obfuscation.orchestration-vnext
rtl-obfuscation.mapping-vnext
rtl-obfuscation.mapping-execution-vnext
rtl-obfuscation.metrics-vnext
rtl-obfuscation.rate-selection-vnext
rtl-obfuscation.rate-metrics-vnext
rtl-obfuscation.restore-vnext
rtl-obfuscation.cli-vnext
```

允许的扩展只有：`categories`、`selected_categories`、`abi_categories` 和 records 中出现新增的
canonical category 值。字段形状、portable path、manifest/range/hash 和 deterministic JSON
规则不得改变。

## 8. Cleanup manifest 与 replacement coverage

### 8.1 必须删除的旧非 RISC 测试

以下路径只冻结旧 CLI、legacy inventory/mapping/profile、固定 count/digest 或已由 vNext 不变量
覆盖；T056 授权逐项删除：

```text
tests/test_all_category_rewrite.py
tests/test_debug_mode.py
tests/test_enum_value_rewrite.py
tests/test_example_fifo_project.py
tests/test_genvar_rewrite.py
tests/test_hierarchy_name_rewrite.py
tests/test_interface_member_rewrite.py
tests/test_interface_rewrite.py
tests/test_localparam_rewrite.py
tests/test_module_port_rewrite.py
tests/test_multi_signal_rewrite.py
tests/test_multifile_project.py
tests/test_parameter_dimension_rewrite.py
tests/test_project_regression.py
tests/test_project_root_low_risk.py
tests/test_project_root_parameter_rewrite.py
tests/test_project_root_parameters.py
tests/test_project_root_rewrite.py
tests/test_signal_net_rewrite.py
tests/test_struct_field_rewrite.py
tests/test_struct_type_rewrite.py
tests/test_subroutine_rewrite.py
tests/test_supported_integration.py
tests/test_t033_impact_category.py
tests/test_t034_single_file_default_profile.py
tests/test_t035_profile_unification.py
tests/test_t036_encryption_rate.py
tests/test_t038_risc_v_parameter_genvar_rate.py
tests/test_typedef_rewrite.py
tests/test_union_field_rewrite.py
tests/test_value_parameter_rewrite.py
tests/test_variable_inventory.py
tests/test_variable_ranges.py
tests/test_variable_rewrite.py
```

删除前必须先建立以下 replacement：

| 删除文件组 | 仍有效的语义 | T056 replacement |
| --- | --- | --- |
| `test_all_category_rewrite.py`、13 个单类别 rewrite 测试、`test_subroutine_rewrite.py`、`test_supported_integration.py` | default 13 类、function/task call、argument body reference、module-local typedef/aggregate/member、one-pass gate/restore | `tests/test_vnext_category_closure.py` 对 `rtl_samples/11_supported_obfuscation.sv` 的 default-13 actual gate；不迁移旧 count、offset、mapping v1 |
| `test_module_port_rewrite.py`、`test_interface_rewrite.py`、`test_interface_member_rewrite.py`、`test_t033_impact_category.py` | module/port/interface/member/modport binding、ABI opt-in、selected-top boundary | T033 19 类 graph/policy/mapping/gate/restore，加 FIFO actual ABI gate |
| `test_parameter_dimension_rewrite.py`、`test_project_root_parameter_rewrite.py`、`test_project_root_parameters.py`、`test_t038_risc_v_parameter_genvar_rate.py` | dimension、named override、shadow owner、genvar/iteration parameter 分离、type parameter fail-closed | 保留并升级后的 `test_symbol_graph_parameters.py`、`test_symbol_graph_genvars.py`、`test_rewrite_policy.py`、`test_mapping_vnext.py` |
| `test_multifile_project.py`、`test_project_regression.py`、`test_project_root_low_risk.py`、`test_project_root_rewrite.py`、`test_example_fifo_project.py` | SourceSet closure/order/decoy、project-root/filelist 对等、actual multi-file gate/restore | retained SourceSet/SourceCatalog/project-root tests，T033 normalized MappingVNext identity，`test_encrypt_demo.py` FIFO actual ABI gate |
| `test_t034_single_file_default_profile.py`、`test_t035_profile_unification.py` | 三入口统一 category 语义、alias、非法输入和事务失败 | product-only registry、retained CLI/orchestration/project-root tests；旧 profile/mapping v2/v3/v4 不迁移 |
| `test_t036_encryption_rate.py` | rate selection、有效行、selected gate、restore、metrics | `test_rate_vnext.py`、`test_rate_execution_vnext.py`、`test_rate_metrics_vnext.py`、`test_metrics_vnext.py` |
| `test_debug_mode.py` 及上述文件中的旧 debug/legacy CLI/schema/count/hash 断言 | 无当前产品语义 | 明确删除；`tests/test_vnext_product_surface.py` 验证七个旧 operation 和 legacy v1/v2/v3/v4 report 全部拒绝 |
| 上述旧测试中的 strict compile/decrypt/Formal | actual gate、byte identity、一个正例和一个功能负例 | retained vNext execution/restore tests、三个 replacement gate，以及第 10.3 节唯一 compact Formal |

不得迁移旧 mapping version、旧 profile 名、旧 debug 目录布局、旧固定 count/hash 或 exact random name。

### 8.2 必须保留并按需更新

以下是新架构测试，不得删除：

```text
tests/test_source_set.py
tests/test_source_catalog.py
tests/test_symbol_graph_signals.py
tests/test_symbol_graph_genvars.py
tests/test_symbol_graph_parameters.py
tests/test_rewrite_policy.py
tests/test_mapping_vnext.py
tests/test_rewrite_vnext.py
tests/test_mapping_execution_vnext.py
tests/test_metrics_vnext.py
tests/test_rate_vnext.py
tests/test_rate_execution_vnext.py
tests/test_rate_metrics_vnext.py
tests/test_orchestration_vnext.py
tests/test_cli_vnext_encryption.py
tests/test_restore_vnext.py
tests/test_project_root_vnext.py
```

`tests/test_project_root_inspect.py` 必须改成 discovery/SourceSet 边界测试，不再调用
`inspect-project`。`tests/test_formal_equivalence.py` 必须用 actual `encrypt-vnext` gate。
`tests/test_encrypt_demo.py` 必须验证更新后的非 RISC vNext demo。

### 8.3 T057 保留项

以下路径不得在 T056 删除或修改；它们是 T057 唯一允许处理的 residual RISC acceptance stack：

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/category_profile.py
rtl_obfuscator/formal_view.py
scripts/t029_acceptance.py
tests/test_risc_v_vector_project_root.py
rtl_samples/RISC-V-Vector/**
```

`rtl_obfuscator/project.py` 只允许为 discovery 抽取做机械 re-export/import 调整；不得修复或扩展其
legacy inventory/analyze 行为，并与上述路径一并视为 residual stack。T057 必须最终替换或删除
这些 residual。

## 9. 允许修改的文件

### 9.1 实现与入口

```text
rtl_obfuscator/category_registry_vnext.py       # 新增
rtl_obfuscator/project_discovery.py             # 新增
rtl_obfuscator/source_set.py
rtl_obfuscator/source_catalog.py
rtl_obfuscator/symbol_graph.py
rtl_obfuscator/rewrite_policy.py
rtl_obfuscator/mapping_vnext.py
rtl_obfuscator/rewrite_vnext.py
rtl_obfuscator/orchestration_vnext.py
rtl_obfuscator/restore_vnext.py
rtl_obfuscator/rewrite.py
rtl_obfuscator/project.py                       # 仅 discovery 抽取兼容
encrypt.py
```

`metrics_vnext.py`、`rate_vnext.py`、`rate_execution_vnext.py`、`rate_metrics_vnext.py` 已按 generic
mapping record 工作，不在允许列表。若新增 category 迫使修改它们，先记录具体硬编码位置并停止。

### 9.2 测试

允许新增：

```text
tests/test_vnext_category_closure.py
tests/test_vnext_product_surface.py
```

允许修改第 8.2 节列出的新架构测试，以及：

```text
tests/test_project_root_inspect.py
tests/test_formal_equivalence.py
tests/test_encrypt_demo.py
```

允许删除且只能删除第 8.1 节逐项列出的 34 个测试文件。

### 9.3 文档

```text
README.md
docs/systemverilog_renaming_table.md
docs/formal_verification.md
docs/future_work.md
docs/three_mode_refactor_plan.md
docs/tasks/T056_vnext_product_convergence.md
```

不允许修改 fixture、RTL sample、Formal 脚本、RISC 文件、历史任务合同或其他文件。需要修改允许
列表外文件时，先在本合同“偏差或阻塞”记录并停止。

## 10. 固定测试 oracle

### 10.1 19 类 replacement coverage

`tests.test_vnext_category_closure` 必须至少覆盖：

1. registry/default/alias：
   19 类 canonical 顺序固定；default/`all` 为前 13 类；`struct`/`interface` alias、去重、乱序归一
   和 unknown/空/非法 ABI 输入正确。
2. default-13 single-file gate：
   对只读 `rtl_samples/11_supported_obfuscation.sv` 使用无 top 的 single-file SourceSet 和
   `DEFAULT_CATEGORIES`。renamed records 的 category 集合必须恰好覆盖 13 个 default category；
   module value parameter 可以因 ABI 保留，但两个 localparam 必须 rename；module-local
   `state_t`、`pair_t`、`payload_t` 及其 field 必须分类为 `internal` 并 rename；
   `apply_mask`、`select_value` 必须各包含真实 call occurrence，arguments 必须包含 body
   reference。actual gate strict compile 0/0，restore byte-identical。
3. T033 19 类 compact gate：
   19 个 category 均产生 registry-backed owner 和 byte-backed ranges；使用全部
   `CANONICAL_CATEGORIES` 与 `MODULE_ABI_CATEGORIES`。selected top module/ports/parameter 以及
   top 内 interface instance 保持 `selected_top_boundary`；其余 fixture 中 eligible category
   必须实际 rename。actual project-root gate strict compile 0/0，restore byte-identical，
   closure 外 `decoy.sv` 不进入 gate。
4. FIFO 多文件 ABI gate：
   更新 `encrypt.py`，使 demo 除选择 19 类外还显式传入全部 11 个 ABI category。对
   `rtl_samples/example_fifo` 的 actual project-root gate，`mapping.selection.abi_categories`
   必须等于 `MODULE_ABI_CATEGORIES`；除 top-boundary `interface_instances` 外，fixture 中有
   candidate 的 canonical category 必须至少有一个 rename record；function/task call、
   module/port named connection、interface/member/modport reference 必须有 byte-backed
   occurrence。strict compile 0/0，独立 decrypt byte-identical。不得恢复旧 FIFO exact count/hash。
5. filelist/project-root MappingVNext identity：
   对 T033 project-root 和等价 closure filelist 分别构建 SymbolGraph、RewritePolicy 和
   MappingVNext；测试注入同一个 deterministic name factory。只去除 `source_set.origin` 后，
   mapping 的 symbol_id、category、owner、ranges、action、reason 和 manifest 必须一致。不得用
   只比较 SymbolGraph 的测试冒充 mapping identity。
6. owner/range/fail-closed：
   function return/argument、same-spelling owner、named override/connection、aggregate
   member、interface/modport、generate/genvar 和 T038 iteration parameter 保持独立；
   registry 外 owner、不同 symbol 的 exact/partial range overlap、非法 top/source/ABI 输入必须
   稳定失败且不发布输出。同一 category/name/owner/range 的重复 elaboration 可以幂等归一。
7. 所有 replacement 测试都不得断言旧 1091/5741/5527、旧 mapping version、旧 profile、
   exact random name 或旧固定 token count。

### 10.2 产品表面与组合回归

`tests.test_vnext_product_surface` 必须至少覆盖：

1. parser 只提供 `encrypt-vnext` / `decrypt-vnext`，七个删除 operation 均非零、无 traceback、
   无输出；
2. 独立进程导入 `rtl_obfuscator.rewrite` 不加载 `inventory`、legacy `project`、
   `formal_view`、`category_profile`；retained orchestration/CLI/restore tests 继续以 mock
   blocker 证明实际 encrypt/decrypt 路径不会调用 legacy builder。本任务不再要求为观察
   `sys.modules` 而给产品增加 probe、hook 或调试输出；
3. 对代表性 legacy report 循环设置 `version` 为 1、2、3、4，四种输入均被
   `decrypt-vnext` 以同一个稳定 report-invalid 错误 fail-closed 拒绝，且不发布输出；
4. single/filelist/project-root 的 no-rate/rate、portable report、metrics、restore 与事务失败保持；
5. 同一进程执行完整显式目标回归，修复当前 T055 后 stale project-root 负例，无顺序污染；
6. README 当前命令只指向 vNext，历史任务链接不作为产品入口。

### 10.3 compact Formal

本任务产生 rewritten RTL，必须通过实际最终 CLI gate 运行：

```text
gold filelist: tests/fixtures/refactor_symbol_graph_parameters/design.f
gold root: tests/fixtures/refactor_symbol_graph_parameters
gate: encrypt-vnext filelist + top + rate=0.35 的 actual selected gate
top: parameter_top
seq: 5
```

正例退出 0，最后一行 JSON 包含 `formal_equivalence=pass`。负例只能从该 actual gate 复制后插入
一个 ASCII `~`；negative strict compile 仍为 catalog/top-overlay 0/0，Formal 必须非零并包含
`unproven` 和 `equiv_status -assert`。

该 Formal 可由目标 unittest 子进程执行，但执行记录必须写出 gold、actual gate、top、完整命令、
退出码和 JSON/失败摘要。不得运行 RISC Formal，不得用 identity comparison、restore 后的 gold
或 legacy gate。

## 11. 目标验收命令

重新审定后的 correction baseline 命令：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_vnext_category_closure tests.test_vnext_product_surface tests.test_encrypt_demo -v
```

现有测试预期通过；它只记录 correction 起点，不代表第 10 节新 oracle 已满足。主 Agent在第
19 节记录的 sample11/FIFO 诊断是冻结的已知失败，不要求子 Agent在修改前增加额外 probe。
子 Agent应先把第 10.1.2、10.1.3、10.1.4、10.1.5 和 10.2.3 的断言写入允许测试，再修实现。

最终验收命令只有以下四条：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_mapping_execution_vnext tests.test_metrics_vnext tests.test_rate_vnext tests.test_rate_execution_vnext tests.test_rate_metrics_vnext tests.test_orchestration_vnext tests.test_cli_vnext_encryption tests.test_restore_vnext tests.test_project_root_vnext tests.test_project_root_inspect tests.test_formal_equivalence tests.test_encrypt_demo tests.test_vnext_category_closure tests.test_vnext_product_surface -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/*.py encrypt.py scripts/formal_equivalence.py tests/test_*.py
git diff --check HEAD
rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T056_vnext_product_convergence.md
```

第一条是同一 Python 进程中的显式非 RISC 回归，明确排除
`tests.test_risc_v_vector_project_root`，不得替换成 blanket discovery。主 Agent只复跑同四条命令。

## 12. 子 Agent执行记录

开始前将状态改为 `IN_PROGRESS` 并填写：

```text
status: READY_FOR_REVIEW
starting_head: 11b76c7cd1a9f433584860e27d664a0158f17bc4
start_time: 2026-07-27T10:01:29+08:00
starting_worktree: `git status --short --branch` -> `## main...origin/main [ahead 12]`; existing T056 implementation/deletion changes plus pre-existing `docs/three_mode_refactor_plan.md` modification; no unrelated files
baseline_command: `conda run -n rtl_obfuscation python -m unittest tests.test_vnext_category_closure tests.test_vnext_product_surface tests.test_encrypt_demo -v`
baseline_result: exit_code=0; `Ran 16 tests in 1.888s`; `OK`
allowed_files: `rtl_obfuscator/source_catalog.py`, `rtl_obfuscator/symbol_graph.py`, `rtl_obfuscator/rewrite_policy.py`, `rtl_obfuscator/mapping_vnext.py`, `encrypt.py`, `tests/test_vnext_category_closure.py`, `tests/test_vnext_product_surface.py`, `tests/test_encrypt_demo.py`, `README.md`, `docs/systemverilog_renaming_table.md`, and `docs/tasks/T056_vnext_product_convergence.md`; no fixture, Formal script, RISC artifact, discovery/orchestration/rate/metrics/rewrite_vnext/restore_vnext, extra deletion, or legacy-path changes
changed_files_from_git_diff_name_status_HEAD: `M README.md`; `M docs/formal_verification.md`; `M docs/future_work.md`; `M docs/systemverilog_renaming_table.md`; `M docs/three_mode_refactor_plan.md` (pre-existing); `M encrypt.py`; `M rtl_obfuscator/mapping_vnext.py`; `M rtl_obfuscator/project.py`; `M rtl_obfuscator/rewrite.py`; `M rtl_obfuscator/rewrite_policy.py`; `M rtl_obfuscator/source_catalog.py`; `M rtl_obfuscator/source_set.py`; `M rtl_obfuscator/symbol_graph.py`; `M tests/test_cli_vnext_encryption.py`; `M tests/test_encrypt_demo.py`; `M tests/test_formal_equivalence.py`; `M tests/test_mapping_execution_vnext.py`; `M tests/test_mapping_vnext.py`; `M tests/test_orchestration_vnext.py`; `M tests/test_project_root_inspect.py`; `M tests/test_project_root_vnext.py`; `M tests/test_rate_execution_vnext.py`; `M tests/test_rate_metrics_vnext.py`; `M tests/test_rate_vnext.py`; `M tests/test_restore_vnext.py`; `M tests/test_rewrite_policy.py`; `M tests/test_rewrite_vnext.py`; `M tests/test_symbol_graph_genvars.py`; `M tests/test_symbol_graph_parameters.py`; `M tests/test_symbol_graph_signals.py`; authorized `D` entries: the 34 files listed in `deleted_files`
untracked_files: `docs/tasks/T056_vnext_product_convergence.md`, `rtl_obfuscator/category_registry_vnext.py`, `rtl_obfuscator/project_discovery.py`, `tests/test_vnext_category_closure.py`, `tests/test_vnext_product_surface.py`
deleted_files: `tests/test_all_category_rewrite.py`, `tests/test_debug_mode.py`, `tests/test_enum_value_rewrite.py`, `tests/test_example_fifo_project.py`, `tests/test_genvar_rewrite.py`, `tests/test_hierarchy_name_rewrite.py`, `tests/test_interface_member_rewrite.py`, `tests/test_interface_rewrite.py`, `tests/test_localparam_rewrite.py`, `tests/test_module_port_rewrite.py`, `tests/test_multi_signal_rewrite.py`, `tests/test_multifile_project.py`, `tests/test_parameter_dimension_rewrite.py`, `tests/test_project_regression.py`, `tests/test_project_root_low_risk.py`, `tests/test_project_root_parameter_rewrite.py`, `tests/test_project_root_parameters.py`, `tests/test_project_root_rewrite.py`, `tests/test_signal_net_rewrite.py`, `tests/test_struct_field_rewrite.py`, `tests/test_struct_type_rewrite.py`, `tests/test_subroutine_rewrite.py`, `tests/test_supported_integration.py`, `tests/test_t033_impact_category.py`, `tests/test_t034_single_file_default_profile.py`, `tests/test_t035_profile_unification.py`, `tests/test_t036_encryption_rate.py`, `tests/test_t038_risc_v_parameter_genvar_rate.py`, `tests/test_typedef_rewrite.py`, `tests/test_union_field_rewrite.py`, `tests/test_value_parameter_rewrite.py`, `tests/test_variable_inventory.py`, `tests/test_variable_ranges.py`, `tests/test_variable_rewrite.py` (34 authorized legacy tests; replacement coverage was established before deletion)
commands: baseline `conda run -n rtl_obfuscation python -m unittest tests.test_vnext_category_closure tests.test_vnext_product_surface tests.test_encrypt_demo -v`; final `conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_mapping_execution_vnext tests.test_metrics_vnext tests.test_rate_vnext tests.test_rate_execution_vnext tests.test_rate_metrics_vnext tests.test_orchestration_vnext tests.test_cli_vnext_encryption tests.test_restore_vnext tests.test_project_root_vnext tests.test_project_root_inspect tests.test_formal_equivalence tests.test_encrypt_demo tests.test_vnext_category_closure tests.test_vnext_product_surface -v`; final `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/*.py encrypt.py scripts/formal_equivalence.py tests/test_*.py`; final `git diff --check HEAD`; final `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T056_vnext_product_convergence.md`
results: correction baseline exit_code=0, `Ran 16 tests in 1.888s`, `OK`; final unittest exit_code=0, `Ran 174 tests in 9.416s`, `OK`; final py_compile exit_code=0 with no output; final diff check exit_code=0 with no output; final status guard exit_code=0 with output `- 状态：READY_FOR_REVIEW`
category_coverage: all 19 canonical categories are registered, ordered, and exercised in the single SourceCatalog -> SymbolGraph -> RewritePolicy -> MappingVNext path: `signals`, `parameters`, `enum_values`, `genvars`, `functions`, `tasks`, `arguments`, `instances`, `generate_blocks`, `typedefs`, `struct_types`, `struct_fields`, `union_fields`, `modules`, `ports`, `interfaces`, `interface_instances`, `interface_ports`, `modports`; default/all, struct/interface aliases, ABI selection, owner/provenance/range audit, top closure, and project-root/equivalent-filelist coverage pass; full-category T033 project-root actual gate selects all 19 categories and all 11 ABI-capable categories, with 4 physical files, 41 mapping records, 81 modified tokens, strict compile 0/0, selected-top boundaries preserved, and byte-identical restore; FIFO all-category product gate also passes with 4 files, 81 records, 105 modified tokens, strict compile 0/0, and byte-identical restore
legacy_surface: product parser exposes only `encrypt-vnext` and `decrypt-vnext`; the seven old product operations are rejected without traceback; product import/runtime does not load legacy inventory/category-profile/formal-view modules; legacy mapping input is rejected without output; SourceSet uses `project_discovery`, and no legacy collector or second SymbolGraph is used
replacement_coverage: the 34 deleted tests are covered by the new 19-category closure and product-surface tests plus the retained/upgraded SourceSet, SourceCatalog, SymbolGraph, RewritePolicy, MappingVNext, gate, mapping envelope, metrics, rate, orchestration, CLI, restore, project-root, inspect, Formal, and demo suites; the corrected replacement rerun passed 13/13 and includes plain-module semantic activation, same-spelling owner separation, exact/partial range conflict fail-closed, actual ABI rename/gate/restore, secure random product naming, registry-only owner validation, and unique discovery identity
correction_commands: baseline `conda run -n rtl_obfuscation python -m unittest tests.test_vnext_category_closure tests.test_vnext_product_surface tests.test_encrypt_demo -v`; final `conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_mapping_execution_vnext tests.test_metrics_vnext tests.test_rate_vnext tests.test_rate_execution_vnext tests.test_rate_metrics_vnext tests.test_orchestration_vnext tests.test_cli_vnext_encryption tests.test_restore_vnext tests.test_project_root_vnext tests.test_project_root_inspect tests.test_formal_equivalence tests.test_encrypt_demo tests.test_vnext_category_closure tests.test_vnext_product_surface -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/*.py encrypt.py scripts/formal_equivalence.py tests/test_*.py`; `git diff --check HEAD`; `rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T056_vnext_product_convergence.md`
correction_results: baseline exit_code=0, `Ran 16 tests in 1.888s`, `OK`; final unittest exit_code=0, `Ran 174 tests in 9.416s`, `OK`; final py_compile exit_code=0 with no output; final diff check exit_code=0 with no output; final status guard exit_code=0 with output `- 状态：READY_FOR_REVIEW`
correction_category_coverage: sample11 default-13 actual gate/restore passed with 1 file, 41 records, 85 modified tokens, and strict compile 0/0; T033 actual full-category ABI gate/restore passed with 4 files, 41 records, 81 modified tokens, all 19 selected categories and all 11 ABI categories; FIFO actual full-category ABI gate/restore passed with 4 files, 81 records, 268 modified tokens, all 11 ABI categories explicitly selected, strict compile 0/0, and byte-identical restore
correction_identity_and_legacy: T033 project-root/filelist actual MappingVNext normalized identity passed; legacy versions 1, 2, 3, and 4 each fail-closed without output; existing import isolation and retained legacy mock blockers pass
correction_implementation: module-local typedef/struct/union types and fields now classify as internal; shared aggregate and interface bindings retain ABI classification; semantic type tokens, aggregate dimensions, nested member paths, interface ports, modport headers, and modport-bound hierarchical references are byte-backed and rewritten together; `encrypt.py` passes all 11 ABI categories explicitly; T033 tests compare actual MappingVNext reports and T033 actions/reasons; sample11 and FIFO actual gate/restore oracles are in replacement coverage
formal_verification: PASS
gold: `tests/fixtures/refactor_symbol_graph_parameters/design.f`
gate: actual final `encrypt-vnext` CLI gate from the compact parameter filelist rate path, with portable gate/report publication
top: `parameter_top`
command: `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/fixtures/refactor_symbol_graph_parameters/design.f --gold-root tests/fixtures/refactor_symbol_graph_parameters --gate-filelist <actual CLI gate>/design.f --gate-root <actual CLI gate> --top parameter_top --seq 5`
exit_code: 0
result: positive actual-gate JSON contained `formal_equivalence=pass`
negative_gate: copy of the actual selected CLI gate with one ASCII `~` inserted after the unique `assign data_o = `
negative_command: same `scripts/formal_equivalence.py` flow against the copied negative gate, with `--top parameter_top --seq 5`
negative_exit_code: nonzero
negative_result: strict compile remained catalog/top `0/0`; Formal failed as required, and output contained `unproven` and `equiv_status -assert`
deviations_or_blockers: none; the pre-existing modification to `docs/three_mode_refactor_plan.md` was preserved and not part of T056 changes; no RISC Formal was run by contract
boundaries: no RISC Formal or RISC artifact edits; residual legacy acceptance modules remain outside the product import/dispatch surface for the next cleanup task; SymbolGraph collection is semantic-object driven, with only bounded source-syntax fallback for a semantic generate owner and fail-closed handling when source evidence is absent; unresolved external/top/ABI cases remain fail-closed; no schema, rate, metrics, fixture, or Formal-script changes
review_request: all implementation and replacement coverage checks pass; all four contract commands passed; status is READY_FOR_REVIEW and not ACCEPTED

correction_record: the returned T056 was repaired in the same task. The extended collector now consumes
compiled PySlang semantic objects and does not use whole-file regex/keyword activation; repeated semantic
elaboration is deduplicated only when category/name/owner and byte range agree, while exact/partial/multiple-
owner conflicts fail closed. The full-category test passes all 11 ABI-capable categories as abi_categories and
checks real child ABI renames, selected-top preservation, strict compile, and restore. SourceCatalog now owns
the semantic owner registry, and MappingVNext accepts registry members only. Product orchestration defaults to
secure_name_factory; deterministic factories are test injections. project.py re-exports discovery helpers from
project_discovery.py, with a product test asserting one discovery implementation. Current renaming, Formal, and
future-work documents describe only the vNext product surface; historical command/mapping claims remain only in
task history. No allowed-file or contract-schema expansion was needed.
```

`formal_verification` 必须使用：

```text
formal_verification: PASS | FAIL | BLOCKED
gold:
gate:
top:
command:
exit_code:
result:
negative_gate:
negative_command:
negative_exit_code:
negative_result:
```

不得粘贴完整日志；记录测试数、退出码、19 类 coverage summary、删除列表、首个失败诊断和关键
Formal JSON。

## 13. 偏差或阻塞

当前已知并纳入合同：

- vNext 从 3 类扩展到 19 类是 cleanup 前置 replacement，不是新产品 category；
- 当前组合回归有 T055 后 stale project-root 负例，必须修正测试，不得回退 project-root 支持；
- residual RISC acceptance stack 暂留 T057，但不得进入 product import/dispatch。

出现以下任一情况必须保持 `IN_PROGRESS` 或设为 `BLOCKED`，不得扩大范围：

- 某一 canonical category 无法在唯一 SymbolGraph 中表达，必须调用 legacy collector；
- 需要为 input mode、fixture、module 名或固定 count 增加分支；
- 支持对象的声明/引用 owner 不完整或 physical range 重叠；
- full-category gate 只能通过删除 reference、忽略 diagnostic 或放宽 strict compile；
- 需要改变 portable report schema、rate/metrics 方程或 mapping version；
- 需要修改 fixture、RISC、Formal 脚本、未授权模块或历史任务；
- compact Formal 需要降低证明强度或使用非 actual gate。

## 14. READY_FOR_REVIEW 条件

- 状态严格为 `READY_FOR_REVIEW`，精确状态守卫通过；
- 四条验收命令全部通过；
- sample11 default-13、T033 full-category ABI、FIFO full-category ABI 三个 actual gate 均 strict
  compile 0/0 且 restore byte-identical；
- 19 类全部进入唯一 SymbolGraph；module-local type/field 为 internal，shared/cross-module type
  才进入 ABI；selected-top boundary 保持；
- T033 project-root/filelist 的实际 MappingVNext normalized identity 通过；
- single/filelist/project-root、rate/no-rate 和 normalized report 不变量保持；
- 七个旧 operation 已移除，legacy v1/v2/v3/v4 report 均被拒绝，product import graph 与实际
  builder call path 不进入 legacy stack；
- 第 8.1 节 34 个旧测试全部删除，replacement coverage 已先建立并记录；
- actual final CLI compact Formal 正例通过，固定 `~` 负例按预期失败；
- RISC Formal 未运行，T057 residual stack 未修改；
- 只修改第 9 节允许文件；
- 子 Agent未创建 T057、未设置 `ACCEPTED`、未执行 git add/commit/push。

## 15. 主 Agent验收边界

主 Agent只独立复跑第 11 节四条命令，并审查：

- 19 类 registry、owner/provenance/range 与 ABI/top-boundary；
- 删除测试与 replacement coverage 一一对应；
- product parser/import graph 无 legacy 路径；
- sample11、T033、FIFO 三个冻结 gate/restore oracle；
- T033 project-root/filelist 的实际 MappingVNext normalized identity；
- actual final CLI compact Formal 正负例；
- 文档只把 vNext 描述为当前产品；
- RISC residual 明确留给 T057。

不增加 hidden probe、旧 acceptance driver、blanket discovery 或 RISC Formal，也不在 review
时追加本合同未列出的 per-category fixture。全部通过后由主 Agent填写独立验收记录并设置
`ACCEPTED`；只有随后才能冻结 T057。

## 16. 主 Agent合同冻结记录（2026-07-24）

```text
status: READY
baseline_commit: 11b76c7cd1a9f433584860e27d664a0158f17bc4
decision: preserve all 19 authorized categories; complete replacement coverage before removing legacy product paths
inputs: T039 SourceSet + T040 SourceCatalog + T041-T043 SymbolGraph + T044-T055 vNext pipeline
outputs: one 19-category SymbolGraph/policy/mapping pipeline; vNext-only product CLI; updated current docs
formal_verification: required; actual final CLI compact positive and one-byte functional negative
risc_boundary: no RISC Formal or RISC artifact edits; residual acceptance stack belongs only to T057
forbidden: three-category release, legacy fallback/converter, second graph, mode-specific collector, fixture/count hacks, T057 creation
```

## 17. 主 Agent独立验收记录（2026-07-24，退回修正）

```text
review_head: 11b76c7cd1a9f433584860e27d664a0158f17bc4
review_worktree: implementation/test deletions are within the contract path list; pre-existing docs/three_mode_refactor_plan.md change remains present
unittest: exact section 11 explicit non-RISC command -> exit_code=0; Ran 170 tests in 7.643s; OK
py_compile: exact section 11 command -> exit_code=0
diff_check: `git diff --check HEAD` -> exit_code=0
status_guard: READY_FOR_REVIEW guard matched before this review, exit_code=0
formal_evidence: target suite reported actual final CLI positive PASS and fixed one-byte `~` negative failure as required
decision: NOT_ACCEPTED; returned to IN_PROGRESS because passing commands do not establish the contracted replacement semantics
```

必须修正以下合同违例后重新申请验收：

1. `symbol_graph.py::_collect_extended_symbols()` 以全文件正则和拼写搜索建立 declaration/reference/
   owner，并由 `enum|typedef|function|task|interface|modport` 关键字决定是否启用整套 collector。
   这既是合同禁止的 lexical collector，也是输入形状分支；没有这些关键字的普通 module/port/
   instance 设计会直接跳过新增 category。必须改为消费已编译 PySlang semantic object；受控 syntax
   fallback 只能补一个已经确定 semantic owner 的精确 token，不能创建 owner 或全局找引用。
2. extended collector 的 `add_record()` / `add_occurrence()` 在 occupied range 上静默返回或跳过。
   合同要求 exact duplicate、partial overlap 和 multiple owner 稳定 fail-closed；不得以“先匹配者
   获胜”隐藏冲突。
3. 当前 full-category gate 测试只传 `categories=CANONICAL_CATEGORIES`，没有传任何
   `abi_categories`。因此 modules/ports/interfaces/type ABI 大量保持 preserved；测试只证明 19 个
   category 名出现在 graph/selection 中，没有证明 19 类 replacement。必须逐 category 验证
   declaration/reference owner，并对 11 个 ABI-capable category 执行实际 opt-in；selected top
   boundary 必须保持，eligible child ABI 必须真实改名、strict compile、restore。
4. modules/interfaces 使用 `$unit` owner，type/interface field 使用未注册的字符串 owner，而
   `mapping_vnext.py` 通过 `startswith("type:")` / `startswith("interface:")` 放宽 owner 校验。
   这没有证明 owner 来自唯一 SourceCatalog registry，也使 modules/interfaces 无法正确分类为
   closure 内 eligible ABI。必须建立可验证的 semantic owner registry，mapping validator 只能
   接受 registry 中实际存在的 owner。
5. `orchestration_vnext.run_vnext()` 默认命名器被从 `secure_name_factory` 改成由公开
   `symbol_id` 推导的确定性 SHA-256 名称。该变更未获授权，并让产品重命名可预测；总体计划明确
   只允许测试注入 deterministic factory。恢复安全随机产品默认，确定性只通过测试注入或去除
   `renamed_name`/派生 hash 后比较 normalized 语义。
6. `project_discovery.py` 是从 `project.py` 复制出的第二份 discovery；原
   `ProjectAnalysisError`、`SourceSetDiscovery`、`_discover_files`、`_discover_sourceset` 仍完整
   存在于 `project.py`。合同要求机械迁移并由 legacy project re-export，不允许双实现。
7. 当前产品文档没有完成合同收口：`docs/systemverilog_renaming_table.md`、
   `docs/formal_verification.md`、`docs/future_work.md` 仍把 mapping v2/v4、
   `decrypt-project` 和旧固定 RISC oracle 描述为当前行为。必须按第 9.3、15 节同步；历史证据只
   留在历史任务合同。
8. 加强 `tests/test_vnext_category_closure.py` / `tests/test_vnext_product_surface.py`，让上述
   lexical activation、same-spelling shadow、range conflict、真实 ABI rename、secure product
   naming 和唯一 discovery 在修复前能够失败。不得再次以“170 tests PASS”替代合同不变量审查。

修正边界保持原合同不变：不得恢复 legacy product fallback，不得修改 fixture、RISC artifact、
Formal 脚本或创建 T057；重新完成四条验收命令后再设为 `READY_FOR_REVIEW`。

## 18. 主 Agent独立验收记录（2026-07-24，第二次退回修正）

```text
review_head: 11b76c7cd1a9f433584860e27d664a0158f17bc4
unittest: exact section 11 explicit non-RISC command -> exit_code=0; Ran 173 tests in 8.887s; OK
py_compile: exact section 11 command -> exit_code=0
diff_check: `git diff --check HEAD` -> exit_code=0
status_guard: READY_FOR_REVIEW guard matched before this review, exit_code=0
formal_evidence: target suite executed the actual final CLI positive and fixed one-byte `~` negative flow; both outcomes matched the contract
closed_previous_findings: collector is semantic-object driven; occupied-range exact/partial conflicts against existing symbols fail closed; all ABI categories are passed to the full gate; owner registry is explicit; product naming is secure-random; discovery has one implementation; current docs are vNext-only
decision: NOT_ACCEPTED; returned to IN_PROGRESS because the cleanup replacement oracle and two frozen identity/conflict invariants remain incomplete
```

必须完成以下修正后再申请验收：

1. 第 10.1 节要求逐 category 的 graph/range/gate/restore replacement。当前 full gate 虽传入全部
   19 类与 11 类 ABI opt-in，但只断言少数 category 的 rename；T033 中 function/task 没有实际
   call，且没有证明 `interface_instances` 的可改写上下文。被删除的 subroutine/interface 测试
   原先覆盖了调用引用和接口实例/member 路径。必须复用已有 fixture 或在临时目录构造 compact
   SystemVerilog，逐一证明 19 类至少一个语义对象的 declaration 和所有 bound references 被同一
   mapping 改写、strict compile 通过、restore byte-identical；selected-top boundary 另行断言
   preserved。不得只检查 category 出现在 graph/report。
2. `test_project_root_and_equivalent_closure_have_same_graph_and_mapping_identity` 当前只比较
   `SymbolGraph.to_report()` 和 category Counter，没有构建 RewritePolicy / MappingVNext。必须按
   第 10.1.4 节实际比较去除 origin、随机名和派生 hash 后的 mapping
   owner/range/action/reason identity，测试名与证据必须一致。
3. `SourceSymbol.symbol_id` 仍只由 `category:file:start:end` 组成，没有包含第 5.1 节冻结的
   `semantic_owner`。四类构造路径必须使用同一个稳定 helper，由 category、声明物理位置和
   semantic owner 共同派生；不得包含运行时 object id。
4. extended collector 的 `add_record()` 对同 range、同 category/name/owner 返回已有 record，
   `add_occurrence()` 对同 range、同 provenance 返回；这仍会把两个不同 semantic object 的精确
   冲突静默合并。允许去重的只能是 PySlang 重复暴露的同一 semantic object，必须以已绑定对象
   identity 在 collector 内先归一；两个不同对象落在同一 physical range 必须稳定
   `SYMBOL_GRAPH_RANGE_CONFLICT`。补充能在修复前失败的测试。
5. 第 10.2.2 节的产品表面 oracle 仍只测试一个 `version: 4` legacy mapping，且只检查 import
   `rewrite` 时未加载 legacy 模块。必须覆盖 v1/v2/v3/v4 全部拒绝，并对实际
   `encrypt-vnext`、`decrypt-vnext` 进程证明运行期不加载/调用
   `inventory`、legacy `project`、`formal_view`、`category_profile`，失败时不发布输出。
6. 执行记录的 `changed_files` 与当前工作区不一致：遗漏
   `tests/test_mapping_execution_vnext.py`、`tests/test_symbol_graph_genvars.py`、
   `tests/test_symbol_graph_parameters.py`，同时列入了当前无 diff 的
   `rtl_obfuscator/rewrite_vnext.py`、`rtl_obfuscator/restore_vnext.py`。重新申请前按
   `git diff --name-status HEAD` 记录真实清单；预先存在的
   `docs/three_mode_refactor_plan.md` 继续单独说明。

修正边界不变：不得恢复 legacy product fallback，不得修改 fixture、RISC artifact、Formal
脚本或创建 T057；不得删除更多测试。完成后重新执行且只记录第 11 节四条命令，再设为
`READY_FOR_REVIEW`。

## 19. 主 Agent重新审定与最终 correction 合同（2026-07-24）

本节是两次退回后的最终裁决；与第 18 节冲突时以本节及已同步修改的第 5、8、10、11、14、15
节为准。主 Agent不得在下一次 review 再增加本节之外的实现或 fixture 要求。

### 19.1 对第二次退回条目的裁决

| 第 18 节条目 | 最终裁决 | 原因 |
| --- | --- | --- |
| 19 类每类都必须在 T033 至少有一个 rename | 撤回并替换 | 这是事后强化；T033 的 top-boundary `interface_instances` 合法 preserved。最终使用 sample11、T033、FIFO 三个固定 oracle 覆盖 default、compact ABI 和多文件 binding |
| project-root/filelist 必须比较实际 MappingVNext | 保留 | 第 10.1 原合同已明确要求 policy/mapping identity，当前测试只比较 graph |
| `symbol_id` 必须重新编码 semantic owner | 撤回 | category + declaration physical range 已稳定唯一；owner 是独立 registry-backed 字段，改变 ID 形状没有产品收益且会制造 schema churn |
| 重复 elaboration 必须按 PySlang 运行时 object identity 去重 | 撤回并澄清 | 运行时 identity 不稳定；同 category/name/owner/range 可幂等归一，不同归一 symbol 的 exact/partial overlap 才 fail-closed |
| v1/v2/v3/v4 与运行期 legacy 隔离 | 部分保留 | 四个 legacy version 必须逐一拒绝；隔离证据由独立 import graph 加 retained mock blocker 组成，不增加产品 probe/hook |
| 执行记录文件清单 | 保留为文档修正 | 最终清单必须来自 `git diff --name-status HEAD`，但它不替代功能验收 |

### 19.2 删除测试对账后的新增既有缺口

这两项不是新产品范围，而是第 1、7、8、10 节原本应覆盖但此前 oracle 漏掉的 replacement：

1. `rtl_samples/11_supported_obfuscation.sv` 中 module-local `state_t`、`pair_t`、`payload_t`、
   struct/union fields 当前被统一分类为 `module_abi_requires_top`；这与 default 13 和对象级 ABI
   设计不符。module-local type/field 必须为 `internal`，shared/cross-module type 才进入 ABI。
2. FIFO demo 当前只选择 ABI category，没有传 `--abi-category`，因而不能证明旧 FIFO
   module/port/interface/modport binding 已被 vNext replacement。主 Agent只读诊断确认全部 ABI
   opt-in 时 gate 仍失败，不能把“selected categories 出现在 report”记录为 full-category gate。

34 个删除文件的分组已穷尽且不重叠：

```text
sample11/default-13 (17):
  test_all_category_rewrite, test_enum_value_rewrite, test_genvar_rewrite,
  test_hierarchy_name_rewrite, test_localparam_rewrite, test_multi_signal_rewrite,
  test_signal_net_rewrite, test_struct_field_rewrite, test_struct_type_rewrite,
  test_subroutine_rewrite, test_supported_integration, test_typedef_rewrite,
  test_union_field_rewrite, test_value_parameter_rewrite, test_variable_inventory,
  test_variable_ranges, test_variable_rewrite

compact ABI (4):
  test_interface_member_rewrite, test_interface_rewrite, test_module_port_rewrite,
  test_t033_impact_category

parameter/genvar retained coverage (4):
  test_parameter_dimension_rewrite, test_project_root_parameter_rewrite,
  test_project_root_parameters, test_t038_risc_v_parameter_genvar_rate

project/FIFO retained coverage (5):
  test_example_fifo_project, test_multifile_project, test_project_regression,
  test_project_root_low_risk, test_project_root_rewrite

obsolete profile surface (2):
  test_t034_single_file_default_profile, test_t035_profile_unification

vNext rate replacement (1):
  test_t036_encryption_rate

removed debug surface (1):
  test_debug_mode
```

冻结诊断：

```text
sample11_no_top:
  graph_has_default_13: yes
  wrongly_preserved_as_module_abi: typedefs, struct_types, struct_fields, union_fields
  function_call_and_task_call_occurrences: present

fifo_per_abi_probe:
  pass: struct_fields, modules, ports
  no_eligible_candidate_due_top_boundary: interface_instances
  strict_gate_fail: parameters, typedefs, struct_types, union_fields, interfaces, interface_ports, modports
```

### 19.3 唯一剩余实现清单

子 Agent只完成以下六项；第 17 节八项已经关闭，不得重写已通过的 discovery、随机命名、owner
registry、CLI cleanup 或文档结构：

1. 修正 type/field 的对象级 `internal/module_abi/top_boundary` 分类，并补齐 FIFO 上已判定
   eligible 的 parameter/type/interface/member/modport bound occurrences；不能通过把所有失败对象
   改成 preserved 来制造 gate 通过。若 PySlang 无法提供完整 binding，按第 13 节记录具体对象和
   source range 后停止，不得 lexical 全文搜索。
2. 在 `test_vnext_category_closure.py` 增加第 10.1.2 的 sample11 default-13 actual
   gate/restore oracle，并加强现有 T033 测试到第 10.1.3 的明确 action/reason 集合。
3. 让 `encrypt.py` 显式传入全部 11 个 ABI category；在 `test_encrypt_demo.py` 检查 report 的
   `abi_categories`、FIFO eligible category rename 集合、关键 bound occurrences、strict compile
   和 byte-identical restore。
4. 把现有 T033 project-root/filelist identity 测试改为实际构建并比较 normalized
   RewritePolicy/MappingVNext，不再只比较 SymbolGraph。
5. 在 `test_vnext_product_surface.py` 循环验证 legacy version 1、2、3、4；保留现有 import
   isolation 与 retained mock blockers，不新增运行时调试接口。
6. 用 `git diff --name-status HEAD` 重写执行记录中的真实 changed/deleted files，重新运行第 11
   节四条最终命令并记录真实测试数、Formal 结果和边界。

### 19.4 correction 允许文件

除已经存在的 T056 worktree 变更外，本轮新增修改只允许：

```text
rtl_obfuscator/source_catalog.py
rtl_obfuscator/symbol_graph.py
rtl_obfuscator/rewrite_policy.py
rtl_obfuscator/mapping_vnext.py
encrypt.py
tests/test_vnext_category_closure.py
tests/test_vnext_product_surface.py
tests/test_encrypt_demo.py
README.md
docs/systemverilog_renaming_table.md
docs/tasks/T056_vnext_product_convergence.md
```

若修复需要修改 `rewrite_vnext.py`、orchestration/rate/metrics、fixture、RTL sample、Formal 脚本、
RISC artifact、project discovery 或恢复任何 legacy product path，必须记录阻塞并停止。不得删除
更多测试，不得创建 T057，不得执行 RISC Formal。

### 19.5 最终冻结

```text
status: READY
contract_baseline: correction baseline command -> exit_code=0; Ran 15 tests in 1.760s; OK
review_commands: exactly section 11 four commands
main_agent_extra_probes: forbidden
required_gates: sample11 default-13; T033 full-category ABI; FIFO full-category ABI
required_identity: T033 project-root/filelist normalized MappingVNext
required_legacy_rejection: versions 1, 2, 3, 4
formal: existing compact actual CLI positive and fixed `~` negative only
withdrawn_requirements: owner re-encoding in symbol_id; runtime object-id dedup; every category renamed in T033; runtime sys.modules instrumentation
acceptance_commitment: if this frozen matrix passes and file/RISC boundaries hold, Main Agent sets ACCEPTED without adding another oracle
```

## 20. 主 Agent 最终验收

- 验收 HEAD：`11b76c7cd1a9f433584860e27d664a0158f17bc4`
- 验收日期：`2026-07-27`
- 范围审计：T056 changed/deleted files 与合同授权及 replacement coverage 对账一致；本轮 correction
  未越过第 19.4 节边界；未修改 RTL fixture、Formal 脚本或 RISC artifact；未执行 RISC Formal。
- 冻结 oracle 审阅：sample11 default-13、T033 full-category ABI、FIFO full-category ABI 均通过
  actual vNext 产品路径生成 gate，并覆盖 strict compile 与 byte-identical restore；T033
  project-root/filelist 比较实际 normalized `MappingVNext`；legacy mapping version 1、2、3、4
  均被稳定拒绝。未发现 fixture 名称、固定计数或替代实现绕过。
- 最终回归：

```text
conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_mapping_execution_vnext tests.test_metrics_vnext tests.test_rate_vnext tests.test_rate_execution_vnext tests.test_rate_metrics_vnext tests.test_orchestration_vnext tests.test_cli_vnext_encryption tests.test_restore_vnext tests.test_project_root_vnext tests.test_project_root_inspect tests.test_formal_equivalence tests.test_encrypt_demo tests.test_vnext_category_closure tests.test_vnext_product_surface -v
exit_code=0
Ran 174 tests in 8.909s
OK

conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/*.py encrypt.py scripts/formal_equivalence.py tests/test_*.py
exit_code=0

git diff --check HEAD
exit_code=0

rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T056_vnext_product_convergence.md
exit_code=0
```

- Formal：冻结回归中的 actual vNext gate 正例通过；固定一字节 `~` 负例按预期失败并验证
  `unproven` 与 `equiv_status -assert`。
- 结论：第 19.5 节冻结矩阵和文件/RISC 边界全部满足，T056 由主 Agent 设置为 `ACCEPTED`。
- Git：未执行 `git add`、`commit` 或 `push`；未创建 T057。
