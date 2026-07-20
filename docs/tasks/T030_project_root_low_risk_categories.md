# T030：`project-root + top` 八类低风险对象迁移

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T029 `ACCEPTED`
- 起始提交：`cb37844`
- 产品方向：`project-root + top` 是默认推荐、强审计、安全的主工作流；显式 filelist 保留为兼容/专家模式
- Formal verification：必须 `PASS`

## 1. 单一目标

在不改变 T027—T029 已验收工程发现、top 闭包、mapping v3、manifest、解密和 formal-view
语义的前提下，把 legacy filelist 已实现的下面八个底层 category 迁移到
`project-root + top` 的 selected-top inventory、加密、gate 审计、解密和 debug 链路：

```text
enum_values
genvars
functions
tasks
arguments
generate_blocks
typedefs
union_fields
```

本任务只迁移既有语义，不重命名 `parameters` 或 `modules`，不删除单文件或显式 filelist
入口，不扩大 SystemVerilog 语言边界。任务完成后，project-root 可显式组合 13 个用户选择项、
对应 17 个实际 category；剩余未迁移类别仅为 `parameters` 和 `modules`。

## 2. 为什么本任务暂不改变省略 `--category` 的默认 profile

“project-root 是默认推荐工作流”描述产品入口和后续能力建设方向，不等于本任务必须同时改变
省略 `--category` 时的 category 集合。

T029 已冻结 RISC-V-Vector 在省略 category 时的五组 1091/5741 oracle。一次同时迁移八类、
重算真实工程全部 oracle、扩展 formal view 并改变默认输出，会把小步迁移升级成新的真实工程
交付任务，违反增量实施原则。

因此 T030 固定：

- 省略 `--category` 时仍启用现有五组
  `signals/ports/instances/struct/interface`；
- 八类通过显式、可重复的 `--category` 选择；
- project-root debug 必须覆盖全部 13 个用户选择项；
- T029 的默认 RISC oracle 和已有命令不变；
- 八类在真实大工程上的默认 profile 晋级属于后续独立任务，不得在 T030 顺手完成。

## 3. 子 Agent 角色和开始条件

子 Agent 是实现者和自测者，不是范围制定者或最终验收者。

开始前必须：

1. 完整阅读 `AGENTS.md`、`docs/tasks/README.md`、T027、T028、T029、本合同、
   `docs/systemverilog_renaming_table.md` 和 `docs/formal_verification.md`；
2. 确认没有其他任务处于 `IN_PROGRESS` 或 `READY_FOR_REVIEW`，T030 是唯一 `READY` 任务；
3. 先把本文件状态改为 `IN_PROGRESS`；
4. 在第 20 节记录开始时间、HEAD、首条命令和继承的工作区状态；
5. 确认第 6 节 fixture 与第 7 节 oracle hash 未变化。

实现者不得设置 `ACCEPTED`、commit、push、创建下一任务，或修改第 18 节只读输入。

## 4. 用户可见 CLI 合同

### 4.1 `inspect-project`

下面八个 choice 加入现有 project-root `--category`：

```text
enum_values genvars functions tasks arguments generate_blocks typedefs union_fields
```

示例：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root rtl_samples/example_fifo \
  --top fifo_top \
  --report /tmp/t030-fifo-inspect.json \
  --category enum_values \
  --category functions \
  --category arguments
```

`inspect-project` 的 schema version、退出码、确定性、路径规则和诊断码不变。

### 4.2 `encrypt-project --project-root`

八类可单独或重复组合选择：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --project-root <root> \
  --top <top> \
  --output-dir <gate> \
  --map <mapping.json> \
  --metrics <metrics.json> \
  --category enum_values \
  --category genvars \
  --category functions \
  --category tasks \
  --category arguments \
  --category generate_blocks \
  --category typedefs \
  --category union_fields \
  --name-length 8
```

仍然拒绝 project-root 的 `all`、`parameters`、`modules` 和底层别名
`struct_types/struct_fields/interfaces/interface_instances/interface_ports/modports`。

### 4.3 固定 group 和 actual category 顺序

现有五组顺序保持不变，八类追加在后，避免改变已有显式五组 mapping：

```text
selected_groups:
signals
ports
instances
struct
interface
enum_values
genvars
functions
tasks
arguments
generate_blocks
typedefs
union_fields
```

固定展开：

```text
signals         -> signals
ports           -> ports
instances       -> instances
struct          -> struct_types, struct_fields
interface       -> interfaces, interface_instances, interface_ports, modports
enum_values     -> enum_values
genvars         -> genvars
functions       -> functions
tasks           -> tasks
arguments       -> arguments
generate_blocks -> generate_blocks
typedefs        -> typedefs
union_fields    -> union_fields
```

用户传参顺序和重复项不得改变 canonical `selected_groups` / `selected_categories` 顺序。

### 4.4 默认 profile

省略 category 时固定仍为：

```text
signals ports instances struct interface
```

FIFO 默认结果继续为 4 files / 50 entries / 195 tokens；RISC 默认结果继续为
19 files / 1091 entries / 5741 tokens。

### 4.5 project-root debug

debug 从同一 gold 独立运行全部 13 个用户选择项，顺序与 4.3 一致。stdout 固定包含：

```json
{"debug":true,"mode":"project-root","category_count":13,"runs":[]}
```

每个 run 继续产生 `gate/`、`mapping.json`、`metrics.json` 和 `maps/`。debug 冲突参数规则不变。

## 5. 语义边界

八类严格继承现有 legacy 定义：

| Category | 本任务包含 | 本任务不包含 |
| --- | --- | --- |
| `enum_values` | reachable module 内 enum member 及已绑定普通引用 | package/class enum、宏无法定位的 token |
| `genvars` | 已支持的 module loop-generate genvar 声明、header 和展开 body 引用 | 任意嵌套/conditional generate、外部层次引用、扩大现有迭代边界 |
| `functions` | reachable module 内有 body 的普通 function 声明、返回变量写入和普通调用 | extern、DPI、package/class function、层次调用 |
| `tasks` | reachable module 内有 body 的普通 task 声明和普通调用 | extern、DPI、package/class task、层次调用 |
| `arguments` | 上述 module function/task formal argument 及 body 内绑定引用 | prototype、命名实参左侧、DPI argument |
| `generate_blocks` | 显式 loop-generate block label 声明 | 隐式 `genblkN`、层次路径引用、instance array |
| `typedefs` | reachable module 内非 struct/union 普通 typedef 及已支持类型引用 | package/class typedef、全部 cast/prototype 形式 |
| `union_fields` | reachable module typedef union field 声明及已绑定 member access | tagged union、pattern key、constraint、反射/DPI 依赖 |

所有 category 必须满足：

- 只收 selected top 实例树中的 reachable module 对象；
- 不可达 module 即使与可达 module 位于同一 `.sv`，也不得进入 eligible/preserved 或被改写；
- 同名文本只有在 PySlang symbol identity 相同后才是同一对象；
- macro location 无法唯一回到物理 identifier 时进入 `preserved`，reason=`macro_expansion`；
- 不扫描字符串、注释、directive、未知外部层次路径；
- 不把 function return variable 或 formal argument 再归入 `signals`；
- 不改变 top module、top ports 或现有 top ABI 保护闭包。

## 6. 固定 T030 fixture

固定输入，任务开始后只读：

```text
tests/fixtures/t030_project_root_low_risk/
├── design.f
├── child.sv
└── top.sv
```

固定 top：

```text
lowrisk_top
```

固定定义数为 3：

```text
lowrisk_child
lowrisk_top
unreachable_lowrisk_decoy
```

固定 reachable modules 只有 2 个：

```text
lowrisk_child
lowrisk_top
```

`unreachable_lowrisk_decoy` 与 `lowrisk_child` 同处 `child.sv`，并声明八类同类对象。
它用于证明 selected-top 边界，不得被删除、移动到独立文件或加入 top 层次。

固定文件 SHA-256：

```text
child.sv  beec0e0e8767ede6ca40626791dae3375a4d33bbc2254691b2933a6ecba416aa
top.sv    a33ceb300548dbf5581b7fa3eed61129b57ff58be768d1a6f98226bdf757cdb7
design.f  b5d10edc287c7f96e0759fef7fb91508742be8bb991214e7ec16ad09bfc7d3f6
```

mapping v3 算法下两份 source file 的输入 manifest：

```text
b6f60206f62401865e1ae27b42ad90d178dd92b8ce30585ca529a0c512f20d0a
```

从 `module unreachable_lowrisk_decoy` 到 EOF 的固定 bytes 长度和 SHA-256：

```text
length: 887
sha256: 181f754601aff6e1ff8ba048afd4b0a441d1b79170403e0eb1795ddf69ed41cf
```

## 7. 固定八类 oracle

### 7.1 T030 fixture reachable oracle

| Category | Entries | Tokens |
| --- | ---: | ---: |
| `enum_values` | 2 | 5 |
| `genvars` | 1 | 5 |
| `functions` | 1 | 3 |
| `tasks` | 1 | 2 |
| `arguments` | 3 | 6 |
| `generate_blocks` | 1 | 1 |
| `typedefs` | 2 | 9 |
| `union_fields` | 2 | 5 |
| **合计** | **13** | **36** |

规范化 entry 仅保留下面字段：

```text
category, scope, original_name, declaration, references, occurrences
```

按 mapping entry 既有顺序做 canonical JSON SHA-256，固定为：

```text
7b7c98400cc47b31f4f3935e6f045c0fd7fc69bb50e63ea25fbbc139780957d7
```

fixture 中不可达 decoy 的 legacy 全 compilation 另有 12 entries / 25 tokens；project-root
报告和 mapping 中这 12/25 必须为零，且 decoy module bytes 必须与第 6 节 hash 一致。

### 7.2 T030 fixture 现有五组和 13 组组合 oracle

现有五组显式/default：

| Group | Entries | Tokens |
| --- | ---: | ---: |
| `signals` | 4 | 14 |
| `ports` | 3 | 9 |
| `instances` | 1 | 1 |
| `struct` | 1 | 2 |
| `interface` | 0 | 0 |
| **合计** | **9** | **26** |

显式选择 13 个用户项后的固定结果：

```text
2 files / 22 entries / 62 tokens
```

### 7.3 FIFO 八类 oracle

固定输入：`rtl_samples/example_fifo`，top=`fifo_top`。

| Category | Entries | Tokens |
| --- | ---: | ---: |
| `enum_values` | 3 | 6 |
| `genvars` | 2 | 10 |
| `functions` | 2 | 7 |
| `tasks` | 1 | 2 |
| `arguments` | 4 | 9 |
| `generate_blocks` | 2 | 2 |
| `typedefs` | 2 | 7 |
| `union_fields` | 2 | 6 |
| **合计** | **18** | **49** |

FIFO 八类规范化 entry canonical SHA-256：

```text
45a1515d754fa9f5104228064bbd17f9ebd085f1166c292f0920b44e8afd1968
```

显式选择现有五组加八类后的固定结果：

```text
4 files / 68 entries / 244 tokens
```

project-root 的八类 entry 必须与 legacy filelist mapping 的 category、scope、original name、
declaration、references 和 occurrences 完全一致；随机 `renamed_name` 不参与 digest。

## 8. inventory 实现要求

实现必须扩展 T027 的 `build_top_project_inventory`，不得把 legacy
`_collect_targets(compilation, category)` 直接用于 project-root 后再按文件名过滤。

固定策略：

1. 从 `_selected_nodes(top_instance)` 和 reachable module definitions 选择 target；
2. enum transparent member 必须还原到其 wrapped `EnumValueSymbol`；
3. function/task 只选择有 syntax 和 body 的 module subroutine；
4. arguments 必须属于 reachable module subroutine；
5. generate block 必须保持 legacy 的显式 loop-generate 判断；
6. typedef 与 union type/field 必须按 declaring module 是否 reachable 过滤；
7. 用 source manager location + symbol identity 去重，不得用名称去重；
8. scope 固定为 declaring module 名，不引入新的 `$unit` 低风险类别；
9. eligible/preserved 排序和全局 range 不重复/不重叠门禁保持不变。

允许复用 legacy helper，但调用边界必须传入已经由 selected-top 筛选的 target。

## 9. reference 收集要求

`_top_project_references` 必须扩展为：

- `enum_values`、`arguments`：`NamedValueExpression.symbol is target` 后记录 identifier；
- `genvars`：复用已验收的 header、iteration parameter 和 body identity 逻辑；
- `functions/tasks`：复用 subroutine identity，function return variable 写入归回 function target；
- `typedefs`：复用已绑定 declared type/CST fallback，且只处理筛选后的 alias；
- `union_fields`：仅当 `MemberAccessExpression.member is target` 时记录右侧 member range；
- `generate_blocks`：当前仅声明，无外部层次引用；
- syntax 缺失时只有既有 helper 明确允许的 sourceRange fallback 可用；
- 每个 range 回读源 bytes 必须精确等于 target name。

禁止通过原名全文搜索补引用，禁止根据 diagnostic 文本推断位置。

## 10. mapping v3、gate 审计和解密

mapping v3 schema 不新增字段。八类必须自然进入：

- `selected_groups` / `selected_categories`；
- `entries` 或 macro `preserved`；
- global/per-file occurrence projection；
- metrics；
- gate transformed ranges；
- gate strict reanalysis；
- decrypt semantic audit和 input manifest 恢复。

`_validate_project_root_mapping` 必须：

- 接受八类的 canonical selection；
- 继续拒绝未选择 category、错误顺序、重复选择、布尔 occurrences、越界/错误宽度 range；
- 不放宽 v3 schema、manifest 或 gate token 校验；
- 保持旧五组 mapping v3 和 T029 mapping 可读、可解密、可 formal-align。

## 11. metrics 和 per-file mapping

对所有非空选择：

```text
symbol coverage = 1.0
occurrence coverage = 1.0
effective coverage = 1.0
plaintext leakage rate = 0.0
```

per-file mapping occurrence 的集合并集必须精确等于 global mapping 的全部 occurrence，不能遗漏
function return、argument、genvar body、typedef use 或 union member access。

## 12. 兼容性合同

必须保持：

- 单文件 version 1 CLI、类别和输出不变；
- 显式 filelist version 2 CLI、19 类、debug、decrypt 和 formal 不变；
- project-root 现有五组显式选择结果不变；
- project-root 省略 category 的五组默认结果不变；
- T027 integration 32/107 不变；
- FIFO 默认 50/195 不变；
- RISC 默认 1091/5741、formal alignment 5527 不变；
- mapping v3 schema version 仍为 3，不创建 v4；
- formal-view / formal-align 行为不变。

## 13. 固定测试方法

新增 `tests/test_project_root_low_risk.py`，正好包含以下 13 个 unittest：

```text
test_each_low_risk_group_exact_oracle
test_fixture_combined_mapping_v3_exact_oracle
test_fixture_gate_reinspect_matches_mapping
test_fixture_decrypt_byte_identical
test_unreachable_decoy_unchanged
test_default_profile_remains_five_groups
test_debug_runs_thirteen_groups
test_fifo_low_risk_matches_legacy_ranges
test_fifo_explicit_thirteen_group_summary
test_per_file_mapping_covers_all_occurrences
test_mapping_v3_rejects_low_risk_category_tampering
test_formal_positive_and_functional_negative
test_legacy_filelist_v2_unchanged
```

允许修改 `tests/test_project_root_rewrite.py` 中既有 debug 方法，使其从五组断言更新为本合同的
13 组固定顺序；不得弱化其他 T028 oracle。

测试产生的 gate、mapping、negative 和 restored 只能写 `TemporaryDirectory` 或 `/tmp`。

## 14. 分阶段实施门禁

### Phase A：基线和 API 探针

- 记录完整 82 项基线和 T027/T028/T029 专项基线；
- 重算第 6、7 节 hash/oracle，必须完全一致；
- 记录八类 target 在 `_selected_nodes` 中的实际 PySlang kind、declaringDefinition、syntax/body；
- 若任何 oracle 或 API 与合同不同，记录偏差并停止。

### Phase B：只读 inventory

- 扩展 group validation和 selected-top target collection；
- `inspect-project` 八类单独/组合达到 13/36 fixture、18/49 FIFO；
- decoy 12/25 完全排除；
- 此阶段不开始 gate 改写问题修补。

### Phase C：range 和 mapping 闭环

- 完成八类 reference helper 接入；
- mapping digest、range bytes、scope 和 legacy parity 通过；
- gate strict reanalysis、metrics、per-file union、decrypt byte restore 通过；
- debug 固定 13 runs。

### Phase D：formal 和兼容回归

- FIFO 68/244 formal 正例通过；
- 人为功能负例 formal 必须失败；
- T027/T028/T029 和完整 95 项回归通过；
- 输入 fixture/FIFO/RISC 不变；
- 完成执行记录后设置 `READY_FOR_REVIEW`。

任一阶段失败不得进入下一阶段。

## 15. 固定黑盒验收命令

### 15.1 编译与目标测试

```sh
conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project.py \
  rtl_obfuscator/inventory.py \
  rtl_obfuscator/rewrite.py \
  tests/test_project_root_low_risk.py \
  tests/test_project_root_rewrite.py

conda run -n rtl_obfuscation python -m unittest \
  tests.test_project_root_low_risk -v
```

固定结果：`Ran 13 tests`、`OK`。

### 15.2 fixture 八类 combined encrypt

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --project-root tests/fixtures/t030_project_root_low_risk \
  --top lowrisk_top \
  --output-dir /tmp/rtl_obfuscation_t030/fixture/gate \
  --map /tmp/rtl_obfuscation_t030/fixture/mapping.json \
  --metrics /tmp/rtl_obfuscation_t030/fixture/metrics.json \
  --file-map-dir /tmp/rtl_obfuscation_t030/fixture/maps \
  --category enum_values \
  --category genvars \
  --category functions \
  --category tasks \
  --category arguments \
  --category generate_blocks \
  --category typedefs \
  --category union_fields \
  --name-length 8
```

固定 stdout：

```json
{"files":2,"mapping_entries":13,"modified_tokens":36}
```

必须满足第 6、7、10、11 节全部断言。

### 15.3 fixture gate inspect 和 decrypt

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root /tmp/rtl_obfuscation_t030/fixture/gate \
  --top lowrisk_top \
  --report /tmp/rtl_obfuscation_t030/fixture/gate-report.json \
  --category enum_values \
  --category genvars \
  --category functions \
  --category tasks \
  --category arguments \
  --category generate_blocks \
  --category typedefs \
  --category union_fields

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir /tmp/rtl_obfuscation_t030/fixture/gate \
  --map /tmp/rtl_obfuscation_t030/fixture/mapping.json \
  --output-dir /tmp/rtl_obfuscation_t030/fixture/restored
```

gate report 必须 2 reachable modules、2 files、13/36 renamed inventory、0 parse/semantic error；
decrypt stdout 同为 2/13/36，两个 source file 与 gold byte-identical。

### 15.4 FIFO 显式 13 项组合

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --project-root rtl_samples/example_fifo \
  --top fifo_top \
  --output-dir /tmp/rtl_obfuscation_t030/fifo/gate \
  --map /tmp/rtl_obfuscation_t030/fifo/mapping.json \
  --metrics /tmp/rtl_obfuscation_t030/fifo/metrics.json \
  --file-map-dir /tmp/rtl_obfuscation_t030/fifo/maps \
  --category signals \
  --category ports \
  --category instances \
  --category struct \
  --category interface \
  --category enum_values \
  --category genvars \
  --category functions \
  --category tasks \
  --category arguments \
  --category generate_blocks \
  --category typedefs \
  --category union_fields \
  --name-length 8
```

固定 stdout：

```json
{"files":4,"mapping_entries":68,"modified_tokens":244}
```

### 15.5 FIFO formal 正例和功能负例

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist rtl_samples/example_fifo/design.f \
  --gold-root rtl_samples/example_fifo \
  --gate-filelist /tmp/rtl_obfuscation_t030/fifo/gate/design.f \
  --gate-root /tmp/rtl_obfuscation_t030/fifo/gate \
  --top fifo_top
```

必须退出 0，stdout JSON 包含：

```json
{"formal_equivalence":"pass","seq":5,"top":"fifo_top"}
```

功能负例复制真实 68/244 gate，根据 mapping 找到 `fifo_ctrl.count` 的 renamed signal，把唯一
`count <= count + 1'b1` 改成 `count <= count + 2`，使用相同 formal 命令验证，必须退出非 0并
留下未证明 `$equiv`。不得修改 gold 或先解密 gate。

### 15.6 完整回归和固定输入

```sh
conda run -n rtl_obfuscation python -m unittest discover -s tests -v
conda run -n rtl_obfuscation python scripts/t029_acceptance.py \
  --work-dir /tmp/rtl_obfuscation_t030/t029-regression
git diff --check
git status --short
```

固定完整回归：现有 82 项 + T030 13 项 = `Ran 95 tests`、`OK`。T029 acceptance 必须通过其
原始 1091/5741/5527 oracle。

独立 SHA-256 检查必须证明：

- T030 fixture 三个文件等于第 6 节；
- `rtl_samples/example_fifo/**` 未变化；
- `rtl_samples/RISC-V-Vector/**` 未变化；
- restored fixture/FIFO 中 mapping `files` 全部 byte-identical。

## 16. Formal verification 固定记录

本任务产生 rewritten RTL，因此必须填写：

```text
formal_verification: PASS
gold: rtl_samples/example_fifo + design.f
gate: /tmp/rtl_obfuscation_t030/fifo/gate + design.f
top: fifo_top
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist rtl_samples/example_fifo/design.f --gold-root rtl_samples/example_fifo --gate-filelist /tmp/rtl_obfuscation_t030/fifo/gate/design.f --gate-root /tmp/rtl_obfuscation_t030/fifo/gate --top fifo_top
exit_code: 0
result: {"formal_equivalence":"pass","gate":"/tmp/rtl_obfuscation_t030/fifo/gate","gold":"rtl_samples/example_fifo","seq":5,"top":"fifo_top"}
negative_gate: /tmp/rtl_obfuscation_t030/fifo-negative + design.f
negative_command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist rtl_samples/example_fifo/design.f --gold-root rtl_samples/example_fifo --gate-filelist /tmp/rtl_obfuscation_t030/fifo-negative/design.f --gate-root /tmp/rtl_obfuscation_t030/fifo-negative --top fifo_top
negative_exit_code: 1
negative_result: expected failure; equiv_status -assert reported 3 unproven $equiv cells (127 groups)
```

正例失败、负例错误地通过、跳过或只运行 identity formal 时不得设置 `READY_FOR_REVIEW`。

## 17. 禁止事项

1. 不得迁移或重命名 `parameters`、`modules`。
2. 不得改变省略 category 的五组默认 profile。
3. 不得修改 top、top ports 或现有 top ABI 规则。
4. 不得把 compilation root 当作 selected-top inventory；decoy 12/25 必须排除。
5. 不得用名称扫描、regex 替代 symbol identity 或 source range。
6. 不得扩大 package/class/DPI/extern/tagged union/层次引用等语言边界。
7. 不得修改 mapping schema version、增加 fallback 或兼容层。
8. 不得删除、弱化 gate strict reanalysis、manifest、occurrence audit、decrypt hash 或 formal。
9. 不得修改 fixture、FIFO、RISC、旧 formal inputs 或 oracle 来制造通过。
10. 不得改变 single-file 或 filelist version 1/2 行为。
11. 不得增加依赖或使用 Conda base/system EDA 工具。
12. 不得改动用户已有的无关工作区修改。
13. 不得 commit、push、amend、rebase、reset 或删除用户文件。

## 18. 允许修改和固定只读文件

子 Agent 只允许修改：

```text
rtl_obfuscator/project.py
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_project_root_low_risk.py
tests/test_project_root_rewrite.py          # 仅 debug 13 组兼容断言
docs/tasks/T030_project_root_low_risk_categories.md
```

固定只读：

```text
tests/fixtures/t030_project_root_low_risk/**
tests/fixtures/t027_project_root/**
rtl_samples/example_fifo/**
rtl_samples/RISC-V-Vector/**
scripts/formal_equivalence.py
scripts/t029_acceptance.py
tests/test_risc_v_vector_project_root.py
docs/tasks/T001_*.md ... T029_*.md
README.md
docs/systemverilog_renaming_table.md
docs/formal_verification.md
docs/future_work.md
docs/project_root_top_roadmap.md
```

对外文档由主 Agent 独立验收后结合现有用户修改统一更新，不属于子 Agent 实现范围。

## 19. 偏差或阻塞

当前：`RESOLVED`

主 Agent 独立验收发现低风险 category 的宏生成对象没有遵守本合同第 5 节的
`preserved(reason=macro_expansion)` 规则。最小复现为：

```text
project-root: tests/fixtures/t030_macro_review (temporary review fixture, removed after reproduction)
top: macro_lowrisk_top
category: functions
inspect-project: PASS; 1 eligible symbol / 2 occurrences; declaration is macro-located
encrypt-project: FAIL; TypeError: 'NoneType' object is not subscriptable
failure: rtl_obfuscator/rewrite.py::_project_mapping_entries sorts entry["declaration"]["file"]
```

预期行为是该 function 进入 `inventory.preserved`，reason=`macro_expansion`，不产生 rewrite
entry，并能完成零 eligible-entry 的 mapping v3 加密/解密闭环。当前实现将 low-risk target 的
reason 固定为 `None`，因此 declaration 为 `None` 时在 mapping 构建阶段崩溃。

修复结果：低风险 target 的 reason 现在统一依据 `SourceManager.isMacroLoc` 判定；宏生成对象进入
`preserved`，reason=`macro_expansion`，declaration 保持 `null`，不会生成 eligible mapping entry。
新增回归在临时宏 fixture 上覆盖 inspect、零 eligible-entry 加密、mapping v3 解密和逐文件 byte restore。
该问题已修复；主 Agent 独立复核通过后，T030 已设置为 `ACCEPTED`。

发现偏差时填写并停止扩大范围：

```text
observed_behavior:
minimal_reproduction:
contract_conflict:
proposed_minimal_resolution:
status:
```

## 20. 子 Agent 执行记录

```text
start_time: 2026-07-17 16:58:27 CST
starting_head: cb37844
first_command: `sed -n '1,240p' docs/tasks/README.md && rg --files docs/tasks | sort | rg 'T30|README'`
confirmed_unique_active_task: yes; T030 is the only `READY` task; T028 and T029 are `ACCEPTED`; no task is `IN_PROGRESS` or `READY_FOR_REVIEW`
inherited_worktree_changes: preserved existing user changes in AGENTS.md, README.md, docs/formal_verification.md, docs/future_work.md, docs/project_root_top_roadmap.md, docs/systemverilog_renaming_table.md, docs/tasks/README.md, rtl_samples/README.md, and the prepared T030 task contract plus tests/fixtures/t030_project_root_low_risk/
phase_a: PASS; required contracts were read; T030 was confirmed as the only active task; fixture hashes and the fixed low-risk reachable/decoy oracle were independently checked; default five-group baseline remained 9/26 on the fixture and 50/195 on FIFO.
phase_b: PASS; project-root inventory collects only reachable module targets through legacy semantic collectors; fixture low-risk exact result is 13/36 with canonical digest 7b7c98400cc47b31f4f3935e6f045c0fd7fc69bb50e63ea25fbbc139780957d7; FIFO low-risk exact result is 18/49 with canonical digest 45a1515d754fa9f5104228064bbd17f9ebd085f1166c292f0920b44e8afd1968.
phase_c: PASS; canonical 13-group selection, mapping v3, gate strict reanalysis, per-file occurrence union, debug matrix, manifest audit and byte-identical decrypt passed; fixture combined low-risk is 2/13/36 and explicit FIFO 13-group is 4/68/244.
phase_d: PASS; FIFO formal positive exited 0 with pass JSON; FIFO count+2 functional negative exited 1 with 3 unproven cells; T029 acceptance exited 0 with 1091/5741/5527 and RISC positive/negative; full regression exited 0 with 95 tests.
review_resume_time: 2026-07-20 10:08:50 CST
review_blocker: macro-generated low-risk function had declaration=null but reason=None, causing mapping construction TypeError
review_fix: low-risk target reason now becomes macro_expansion when SourceManager.isMacroLoc(target.location) is true; macro targets are preserved and excluded from eligible mapping
review_macro_result: PASS; temporary macro function inspect reports 0 eligible and 1 preserved macro_expansion object; encrypt returns 2/0/0; decrypt restores defs.svh and top.sv byte-identically
review_target_unittest: PASS; `Ran 13 tests in 5.316s`, `OK`
review_full_unittest: PASS; `Ran 95 tests in 127.025s`, `OK`
finish_time: 2026-07-20 10:08:50 CST
ending_head: cb37844
```

## 21. READY_FOR_REVIEW 交付证据

完成后必须填写：

```text
changed_files: rtl_obfuscator/project.py; rtl_obfuscator/inventory.py; rtl_obfuscator/rewrite.py; tests/test_project_root_low_risk.py; tests/test_project_root_rewrite.py (debug assertion only); docs/tasks/T030_project_root_low_risk_categories.md
exact_commands: `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project.py rtl_obfuscator/inventory.py rtl_obfuscator/rewrite.py tests/test_project_root_low_risk.py tests/test_project_root_rewrite.py`; `conda run -n rtl_obfuscation python -m unittest tests.test_project_root_low_risk -v`; temporary macro fixture inspect/encrypt/decrypt regression; fixed fixture encrypt/inspect/decrypt commands from sections 15.2-15.3; fixed FIFO 13-group encrypt command from section 15.4; fixed FIFO formal positive and count+2 negative commands from section 15.5; prior `conda run -n rtl_obfuscation python scripts/t029_acceptance.py --work-dir /tmp/rtl_obfuscation_t030_t029c`; `conda run -n rtl_obfuscation python -m unittest discover -s tests -v`; fixture hash/decoy assertion; `git diff --exit-code cb37844 -- rtl_samples/example_fifo rtl_samples/RISC-V-Vector`; `git diff --check`; `git status --short`
exit_codes: py_compile=0; target unittest=0; macro inspect/encrypt/decrypt=0/0/0; fixture encrypt/inspect/decrypt=0/0/0; FIFO encrypt/formal positive=0/0; FIFO functional negative=1; T029 acceptance=0; full unittest=0; fixed-input diff=0; git diff --check=0
fixture_hash_result: PASS; child.sv/top.sv/design.f match fixed SHA-256; decoy suffix length=887 and SHA-256 181f754601aff6e1ff8ba048afd4b0a441d1b79170403e0eb1795ddf69ed41cf
fixture_low_risk_result: PASS; each explicit group matches enum_values=2/5, genvars=1/5, functions=1/3, tasks=1/2, arguments=3/6, generate_blocks=1/1, typedefs=2/9, union_fields=2/5; combined mapping is 2 files / 13 entries / 36 tokens with canonical digest 7b7c98400cc47b31f4f3935e6f045c0fd7fc69bb50e63ea25fbbc139780957d7
macro_lowrisk_result: PASS; macro-generated function is preserved with reason=macro_expansion and null declaration; no eligible entry is emitted; zero-entry mapping v3 encryption/decryption is byte-identical
fixture_combined_result: PASS; explicit 13 user groups produce 2 files / 22 entries / 62 tokens; selected group/category order is canonical
unreachable_decoy_result: PASS; decoy 12 entries / 25 tokens are excluded, module suffix is byte-identical, and unrelated files are not copied
fifo_legacy_parity_result: PASS; project-root low-risk mapping matches legacy filelist category/scope/name/declaration/reference ranges exactly; 18 entries / 49 tokens and canonical digest 45a1515d754fa9f5104228064bbd17f9ebd085f1166c292f0920b44e8afd1968
fifo_combined_result: PASS; explicit 13-group FIFO mapping is 4 files / 68 entries / 244 tokens
mapping_v3_result: PASS; canonical selection, schema, ranges, manifests, gate audit and low-risk category tampering rejection all passed
metrics_result: PASS; symbols and occurrences have coverage 1.0, effective coverage 1.0, plaintext leakage rate 0.0 for non-empty selections
per_file_mapping_result: PASS; fixture per-file occurrence union is exactly the 36 global occurrences with no header placeholder
gate_reinspect_result: PASS; fixture gate reinspection reports 2 reachable modules / 2 files / 13 entries / 36 occurrences / 0 parse errors / 0 semantic errors; FIFO gate strict reanalysis also passed
decrypt_hash_result: PASS; fixture restored child/top and FIFO restored closure files are byte-identical and manifests match inputs
debug_matrix_result: PASS; project-root debug independently runs all 13 groups in fixed order and emits gate/mapping/metrics/maps for each
default_profile_result: PASS; omitted category remains signals/ports/instances/struct/interface with fixture 9/26 and FIFO 50/195
legacy_v1_v2_result: PASS; legacy filelist mapping v2 encrypt/decrypt remains unchanged and missing source-root is rejected
risc_t029_result: PASS; T029 acceptance exited 0 with 56 candidates / 17 modules / 19 files / 1091/5741 inventory, 260 formal transformations, 5527 alignment replacements, RISC positive pass and functional negative expected-fail
formal_result: PASS; FIFO 13-group rewritten gate formal command exited 0 with {"formal_equivalence":"pass","seq":5,"top":"fifo_top"}
formal_negative_result: PASS; independent FIFO count+2 mutation exited 1 and `equiv_status -assert` reported 3 unproven cells
target_unittest_result: PASS; `Ran 13 tests in 5.316s`, `OK`
full_unittest_result: PASS; `Ran 95 tests in 127.025s`, `OK`
git_diff_check: PASS; fixed FIFO/RISC inputs have zero diff from cb37844; `git diff --check` exited 0; no commit or push performed
uncovered_boundaries: parameters/modules remain excluded; default profile remains five groups; package/class/DPI/extern/tagged-union/hierarchical-reference boundaries remain unsupported; macro-generated low-risk objects are preserved rather than rewritten; T030 did not modify fixtures, FIFO, RISC or formal inputs
```

证据齐全且所有门禁通过后，子 Agent 只能将状态设置为 `READY_FOR_REVIEW`。

## 22. 主 Agent 独立验收

主 Agent 必须独立执行：

1. 第 15 节全部命令；
2. 八类单组、fixture 13/36、组合 22/62 exact oracle；
3. decoy 12/25 排除和 module bytes hash；
4. FIFO legacy parity 18/49 和组合 68/244；
5. mapping v3 canonical selection、范围、manifest、per-file union和损坏负例；
6. fixture/FIFO gate strict reanalysis和逐文件 byte restore；
7. FIFO formal 正例和真实 gate 功能负例；
8. 原五组 default、single/filelist、T027/T028/T029 全回归；
9. 固定输入、允许文件和工作区无关修改保护。

全部通过后，主 Agent 才能：

- 更新正式文档，把 project-root 标为默认推荐主工作流并记录八类显式选择；
- 将 T030 设置为 `ACCEPTED`；
- 检查 staged diff；
- 执行规定的 commit 和 push。

## 23. 主 Agent 验收结果

```text
accepted_at: 2026-07-20 CST
accepted_head_before_commit: cb37844
target_unittest: PASS; T030 + T027 + T028 project-root suites Ran 47 tests in 20.832s; OK; py_compile=0
full_unittest: PASS; Ran 95 tests in 124.062s; OK
fixture: PASS; low-risk exact 13/36, combined 22/62, decoy excluded, gate reinspection clean, byte restore exact
macro_fixture: PASS; inspect 0 eligible/1 preserved macro_expansion; encrypt 2/0/0; decrypt and both files byte-identical
fifo: PASS; legacy parity 18/49; explicit 13-group mapping 68/244; metrics and per-file occurrences complete
mapping_v3: PASS; canonical selection, ranges, manifests, gate audit and tamper rejection
decrypt: PASS; fixture/FIFO restored closure files byte-identical
formal_positive: PASS; FIFO 13-group gate; exit 0; {"formal_equivalence":"pass","seq":5,"top":"fifo_top"}
formal_negative: PASS; count+2 mutation exited non-zero with unproven equivalence cells
legacy_compatibility: PASS; single/filelist and mapping v1/v2 regression unchanged
risc_regression: PASS; full suite RISC tests passed; prior independent T029 acceptance remained valid after reason-only macro fix
fixed_inputs: PASS; T030 fixture hashes unchanged; FIFO/RISC inputs unchanged
diff_check: PASS; `git diff --check` exit 0
commit: NOT RUN; user requested no commit/push
push: NOT RUN; user requested no commit/push
```

## 25. 主 Agent 独立 review 结果

```text
reviewed_at: 2026-07-20 CST
target_unittest: PASS; T030 + T027 + T028 project-root suites Ran 47 tests in 20.832s; OK
full_unittest: PASS; Ran 95 tests in 124.062s; OK
t029_acceptance: PASS; prior independent run passed closure=19, modules=17, inventory=1091/5741, formal positive and functional negative
fixture_fifo_formal: PASS; independently rerun T030 FIFO 13-group gate exit 0 with formal_equivalence=pass; functional negative exited non-zero
macro_low_risk_review: PASS; temporary macro function inspect/encrypt/decrypt/byte-restore regression passed
fixed_input_hashes: PASS; child.sv/top.sv/design.f match T030 contract
git_diff_check: PASS
acceptance: ACCEPTED
status_action: T030 set to ACCEPTED by Main Agent; no commit or push performed
```

## 24. 主 Agent READY 准备证据

```text
prepared_at: 2026-07-17 CST
prepared_head: cb37844
active_task_check: PASS; T030 is the only READY task; no task is IN_PROGRESS or READY_FOR_REVIEW; historical T006 remains DRAFT
inherited_worktree: existing user changes in AGENTS.md, README.md, docs/formal_verification.md, docs/future_work.md, docs/project_root_top_roadmap.md, docs/systemverilog_renaming_table.md, docs/tasks/README.md, and rtl_samples/README.md were preserved and not edited during T030 preparation
baseline_command: conda run -n rtl_obfuscation python -m unittest discover -s tests -v
baseline_result: PASS; Ran 82 tests in 110.384s; OK
fixture_pyslang: PASS; shared compilation reported 0 errors
fixture_verible: PASS; both source files accepted
fixture_iverilog: PASS; iverilog -g2012 -s lowrisk_top exited 0
fixture_yosys: PASS; read_verilog -sv, hierarchy -check -top lowrisk_top, prep and check exited 0 with 0 problems
fixture_hashes: PASS; child/top/design.f and decoy slice match section 6
fixture_legacy_probe: PASS; full compilation produced 25 entries / 61 tokens; filtering exact semantic scope lowrisk_child produced the fixed reachable 13/36 and canonical digest 7b7c98400cc47b31f4f3935e6f045c0fd7fc69bb50e63ea25fbbc139780957d7; the remaining decoy contribution is exactly 12/25
fixture_current_project_probe: PASS; existing five groups produce 2 files / 9 entries / 26 tokens with 2 reachable modules, 3 definitions, 0 interfaces and 0 errors
fifo_low_risk_legacy_probe: PASS; 4 files / 18 entries / 49 tokens; exact category table and canonical digest 45a1515d754fa9f5104228064bbd17f9ebd085f1166c292f0920b44e8afd1968
fifo_combined_legacy_probe: PASS; existing nine actual categories plus eight low-risk categories produce 4 files / 68 entries / 244 tokens
fifo_combined_formal_probe: PASS; exit 0; {"formal_equivalence":"pass","seq":5,"top":"fifo_top"}
git_diff_check: PASS
ready_decision: READY; fixed input, exact machine-readable outputs, phase gates, allowed files, compatibility boundaries, formal positive and functional negative are all specified
```
