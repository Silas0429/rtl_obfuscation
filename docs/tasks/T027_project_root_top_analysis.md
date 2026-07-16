# T027：`project-root + top` 工程闭包与 AST inventory

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T026 `ACCEPTED`
- 固定 RISC-V-Vector 仓库提交：`5586a30`
- 路线图：[`docs/project_root_top_roadmap.md`](../project_root_top_roadmap.md)
- Formal verification：`N/A`，本任务不产生重写 RTL

## 1. 单一目标

新增可复用的 `inspect-project` 能力。给定一个包含任意层级子目录的 SystemVerilog 工程根目录
和 top module 名，工具必须自动完成：

1. 递归发现 `.sv` / `.svh`；
2. 建立一个文件多 module/interface/package 的定义索引；
3. 解析 active `` `include``、命令行 define、源码宏定义和宏使用依赖；
4. 从唯一 top 开始构建 module/interface/type/include/macro 依赖闭包；
5. 只严格编译该闭包，不让不可达文件的缺失依赖污染 top；
6. 从选定 top 的语义实例开始遍历 AST；
7. 对 signals、ports、instances、struct、interface 五个概念组输出 eligible、preserved、
   unsupported inventory 和精确源码字节区间；
8. 输出稳定、可复现、机器可审计的 JSON 报告和结构化错误。

本任务到“分析和 source ranges”为止，不生成随机名称，不修改 RTL，不生成 gate、mapping、
metrics 或 decrypt 输出。真正的 project-root 加密闭环属于 T028。

## 2. 子 Agent 角色

子 Agent 是本任务的实现者和自测者，不是需求制定者，也不是最终验收者。

子 Agent 必须：

- 完整阅读 `AGENTS.md`、`docs/tasks/README.md`、本任务合同和路线图后再开始；
- 确认本文件是唯一 `READY` 任务，然后先把状态改为 `IN_PROGRESS` 并记录开始时间、HEAD 和
  首条命令；
- 严格在第 15 节允许文件内实现；
- 依次完成第 12 节的内部阶段，不跳过失败门禁；
- 用固定 fixture、固定 RISC 输入和固定 JSON 断言完成黑盒自测；
- 记录实际 PySlang API、所有变更文件、命令、退出码和结果；
- 全部通过后只把状态设置为 `READY_FOR_REVIEW`；
- 不得设置 `ACCEPTED`，不得 commit、push、改写历史或创建后续任务。

主 Agent 保留需求解释、任务边界、oracle、独立验收和最终 `ACCEPTED` 权限。

## 3. 用户可见 CLI 合同

在 `rtl_obfuscator.rewrite` 中新增子命令：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root <directory> \
  --top <module-name> \
  --report <report.json> \
  [--include-dir <relative-or-absolute-directory>]... \
  [--define <NAME-or-NAME=VALUE>]... \
  [--category <group>]...
```

### 3.1 参数

- `--project-root`：必需，必须是存在的目录。
- `--top`：必需，合法 SystemVerilog identifier；本任务不接受 hierarchical path。
- `--report`：必需；父目录不存在时自动创建，已有文件原子覆盖。
- `--include-dir`：可重复。相对路径以 `project-root` 为基准；路径必须位于 project-root 内。
- `--define`：可重复，支持 `NAME` 和 `NAME=VALUE`；无值时按 `1` 处理。
- `--category`：可重复，choices 固定为 `signals`、`ports`、`instances`、`struct`、
  `interface`；省略时启用全部五组。

概念组展开规则：

```text
signals   -> signals
ports     -> ports
instances -> instances
struct    -> struct_types, struct_fields
interface -> interfaces, interface_instances, interface_ports, modports
```

报告永远使用右侧实际 category。已有 `encrypt`、`decrypt`、`encrypt-project`、
`decrypt-project` 和现有底层 category 语义不得变化。

### 3.2 退出码与 stdout

- 成功：退出码 `0`，stdout 只输出一行 JSON summary。
- 工程分析失败：退出码 `1`，仍必须生成 `status=error` 报告，stdout 输出一行 error summary。
- argparse/调用错误：退出码 `2`；不要求生成报告。
- traceback、warning、调试日志不得写入 stdout；必要诊断写 stderr。

integration fixture 成功 stdout 必须精确为一行：

```json
{"candidate_files":7,"closure_files":6,"definitions":6,"eligible_occurrences":107,"eligible_symbols":32,"reachable_interfaces":1,"reachable_modules":3,"status":"pass","top":"project_top"}
```

JSON key 顺序必须固定为上面的顺序，末尾只允许一个换行。

## 4. 文件发现和路径规则

### 4.1 候选文件

- 递归发现普通文件，扩展名只接受小写 `.sv`、`.svh`。
- 不跟随目录 symlink。
- 忽略 `.git`、`.hg`、`.svn`、`__pycache__` 目录。
- 其他文件夹名称不作猜测性排除；只有扩展名决定是否为候选 RTL。
- 所有路径转成 project-root 相对 POSIX 路径并按字典序排序。
- JSON 不得出现绝对 project-root、临时目录或运行机器用户名。

### 4.2 定义索引

- 索引全部候选源中的 module、interface、package 声明；一个文件可有多个定义。
- 每项至少包含 `kind/name/file/start/end`。
- `start/end` 是原始 UTF-8 bytes 的半开区间，回读必须等于定义名。
- 同名 top 无定义时 `TOP_NOT_FOUND`，多定义时 `AMBIGUOUS_TOP`。
- 被 reachable 对象引用的普通 module/interface 多定义时 `AMBIGUOUS_DEFINITION`。
- 不可达文件中的普通重复定义不阻止 top 分析，但仍保留在 definitions 索引中。

## 5. include、宏和编译上下文规则

### 5.1 include 搜索顺序

对 active `` `include "path"``，按以下顺序查找：

1. consumer 文件所在目录；
2. 显式 `--include-dir`，保持命令行顺序；
3. project-root 下包含 `.sv/.svh` 的所有目录，按相对路径字典序。

同一优先级只有一个匹配时选择该文件。最高有效优先级出现多个不同匹配时返回
`AMBIGUOUS_INCLUDE`；无匹配返回 `MISSING_INCLUDE`。显式 include directory 的唯一匹配必须
能消除自动目录中的同名歧义。

inactive `ifdef/ifndef` 分支中的 include 不进入 active dependency edge。命令行 define 优先于
源码 provider，并参与条件求值。

### 5.2 宏 provider

- 对 reachable 源中的 active 宏使用，命令行 define 优先。
- 若没有命令行 define，则查找 project-root 中唯一 active `` `define`` provider。
- 无 provider 返回 `UNRESOLVED_MACRO`。
- 两个及以上无法由 include 关系或唯一先后依赖消歧的 provider 返回 `AMBIGUOUS_MACRO`。
- provider 文件必须加入 closure，并排在 consumer 之前。
- 不得简单按目录遍历顺序选取第一个同名宏。
- 宏展开生成的 identifier 如果不能映射到唯一物理 token，整个 symbol 标为
  `preserved/macro_expansion`；不得猜测或生成虚假 range。

本任务不要求支持宏生成 module/interface/package 声明。遇到这种情况报告
`UNSUPPORTED_MACRO_IDENTIFIER`，不使用正则伪造语义定义。

## 6. top-rooted 设计闭包

闭包从唯一 top 定义开始，反复加入：

- reachable module 实例对应的 module definition；
- reachable interface 实例或 interface port 对应的 interface definition；
- reachable module/interface 使用的 compilation-unit struct/type provider；
- active include provider；
- active macro provider。

闭包稳定后才执行严格 compilation。候选索引可以查看所有文件，但严格 compilation 只能加入
闭包 source files；禁止“编译全部 56 个文件后再过滤报告”。如果一个 closure source file
包含可达和不可达两个 module，该文件整体参与 compilation，但 AST inventory 只能从选定 top
实例树遍历，不得收集不可达 module。

编译要求：

- 使用一个共享 `pyslang.SourceManager`；
- 使用当前环境实际 API `pyslang.syntax.SyntaxTree.fromFiles(...)`，其返回一个组合 SyntaxTree；
- 使用一个共享 compilation unit；
- 设置 `pyslang.ast.CompilationOptions.topModules={top}`；
- 明确找到该 top 的语义实例并从它开始遍历；不能假设 compilation root 只含 top；
- gold 严格 compilation 只要有一个 error diagnostic 就返回 `PARSE_ERROR` 或
  `SEMANTIC_ERROR`，不得继续输出 `status=pass`。

parameter、localparam 和 generate condition 必须参与 elaboration，但不进入本任务 eligible
inventory。不得通过删除 parameter 来简化 AST。

## 7. 报告 schema

成功和失败都使用 schema version 1：

```json
{
  "schema_version": 1,
  "status": "pass",
  "top": "project_top",
  "compile": {
    "compilation_unit": "single",
    "include_dirs": [],
    "defines": [],
    "compile_order": [],
    "parse_errors": 0,
    "semantic_errors": 0
  },
  "candidate_files": [],
  "definitions": [],
  "dependencies": {
    "includes": [],
    "macros": []
  },
  "reachable": {
    "modules": [],
    "interfaces": [],
    "files": [],
    "source_files": [],
    "header_files": []
  },
  "inventory": {
    "eligible": [],
    "preserved": [],
    "unsupported": []
  },
  "diagnostics": []
}
```

### 7.1 inventory entry

```json
{
  "category": "signals",
  "scope": "project_top",
  "name": "top_signal",
  "declaration": {"file":"rtl/top_bundle.sv","start":0,"end":10},
  "references": [],
  "occurrences": 1,
  "reason": null
}
```

- eligible entry：`reason=null`，`declaration` 必须非空，`occurrences=1+len(references)`。
- preserved/unsupported entry：必须有稳定 reason；无法映射物理声明时允许
  `declaration=null`。
- scope 使用语义 scope，不用字符串文件名猜测。compilation-unit struct scope 固定为 `$unit`，
  field scope 固定为 `$unit::<type-name>`。
- range 回读必须精确等于 `name`，ranges 按 `(file,start,end)` 排序、不可重复、不可重叠。

### 7.2 排序与确定性

- candidate/reachable files：路径字典序。
- definitions：`(kind,name,file,start,end)`。
- dependencies：provider/consumer/name 的字典序。
- inventory：`(category,scope,declaration.file,declaration.start,name)`；null declaration 排最后。
- diagnostics：`(file,start,code,message)`，无位置项排最后。
- JSON 使用 UTF-8、两空格缩进、`\n` 换行、文件末尾一个换行。
- 相同命令运行两次，报告 bytes 和 stdout bytes 必须完全一致。

### 7.3 错误码

固定支持：

```text
TOP_NOT_FOUND
AMBIGUOUS_TOP
AMBIGUOUS_DEFINITION
UNRESOLVED_MODULE
UNRESOLVED_INTERFACE
MISSING_INCLUDE
AMBIGUOUS_INCLUDE
UNRESOLVED_MACRO
AMBIGUOUS_MACRO
PREPROCESS_ERROR
PARSE_ERROR
SEMANTIC_ERROR
UNSUPPORTED_MACRO_IDENTIFIER
```

固定负向 fixtures 必须只产生一个 primary diagnostic；其他底层 diagnostics 可以放在
`details`，但不得改变 primary code。

## 8. 固定 integration fixture 与精确 oracle

输入目录：

```text
tests/fixtures/t027_project_root/integration
```

这些 fixture 由主 Agent 在任务进入 `READY` 前冻结。子 Agent不得修改。

### 8.1 发现和定义

- candidate files：7（6 个 `.sv`、1 个 `.svh`）。
- definitions：6（5 个 module、1 个 interface）。
- modules 精确集合：

```text
project_top
project_child
project_leaf
same_file_unused
unrelated
```

- interfaces 精确集合：`internal_if`。
- reachable modules：`project_top`、`project_child`、`project_leaf`。
- reachable interfaces：`internal_if`。
- unreachable modules：`same_file_unused`、`unrelated`。
- closure files：6；唯一排除的候选文件为 `rtl/unused/unrelated.sv`。
- source compile order 精确为：

```text
rtl/bus/internal_if.sv
rtl/types/structs.sv
rtl/core/leaf.sv
rtl/core/child.sv
rtl/top_bundle.sv
```

- header dependency：`include/common.svh`。
- include edges：`internal_if.sv -> common.svh`、`structs.sv -> common.svh`。
- macro provider：`T027_WIDTH -> include/common.svh`。
- parse errors = 0，semantic errors = 0。

### 8.2 eligible symbol oracle

必须是 32 entries / 107 occurrences。精确分组如下：

| Category | Scope | Name | Occurrences |
| --- | --- | --- | ---: |
| signals | `project_top` | `top_signal` | 3 |
| signals | `project_top` | `child_valid` | 3 |
| signals | `project_top` | `child_data` | 3 |
| signals | `project_child` | `child_packet` | 5 |
| signals | `project_child` | `child_signal` | 3 |
| signals | `project_leaf` | `leaf_packet` | 6 |
| signals | `project_leaf` | `leaf_signal` | 4 |
| ports | `project_child` | `clk` | 3 |
| ports | `project_child` | `reset_n` | 3 |
| ports | `project_child` | `child_valid_i` | 3 |
| ports | `project_child` | `child_data_i` | 3 |
| ports | `project_child` | `child_valid_o` | 3 |
| ports | `project_child` | `child_data_o` | 3 |
| ports | `project_leaf` | `clk` | 3 |
| ports | `project_leaf` | `reset_n` | 3 |
| ports | `project_leaf` | `leaf_valid_i` | 4 |
| ports | `project_leaf` | `leaf_data_i` | 3 |
| ports | `project_leaf` | `leaf_valid_o` | 3 |
| ports | `project_leaf` | `leaf_data_o` | 3 |
| instances | `project_top` | `u_child` | 1 |
| instances | `project_child` | `u_leaf` | 1 |
| struct_types | `$unit` | `packet_t` | 3 |
| struct_fields | `$unit::packet_t` | `packet_valid` | 5 |
| struct_fields | `$unit::packet_t` | `packet_payload` | 5 |
| interfaces | `$unit` | `internal_if` | 2 |
| interface_instances | `project_top` | `top_bus` | 7 |
| interface_ports | `internal_if` | `clk` | 2 |
| interface_ports | `internal_if` | `if_request` | 5 |
| interface_ports | `internal_if` | `if_acknowledge` | 5 |
| interface_ports | `internal_if` | `if_data` | 5 |
| modports | `internal_if` | `producer` | 1 |
| modports | `internal_if` | `consumer` | 1 |

top ports `top_clk/top_reset_n/top_valid_i/top_data_i/top_valid_o/top_data_o` 必须出现在 preserved
清单，category=`ports`、reason=`top_port`，不得进入 eligible。`same_file_secret`、`unused_i`、
`unused_o`、`u_missing`、`value_i` 不得出现在任何 reachable inventory。

## 9. 固定 top ABI 和宏展开 fixtures

### 9.1 top ABI

输入：`tests/fixtures/t027_project_root/top_abi`，top=`abi_top`。

必须严格编译 0 error。以下对象不得 eligible：

| Category | Name | Reason |
| --- | --- | --- |
| ports | `packet_i` | `top_port` |
| ports | `bus` | `top_port` |
| ports | `result_o` | `top_port` |
| struct_types | `abi_packet_t` | `top_abi_type` |
| struct_fields | `abi_field` | `top_abi_type` |
| interfaces | `abi_if` | `top_abi_type` |
| interface_ports | `abi_signal` | `top_abi_type` |
| modports | `sink` | `top_abi_type` |

top ABI fixture eligible entries 必须为 0，以上 preserved 集合必须精确相等。

### 9.2 宏展开 identifier

输入：`tests/fixtures/t027_project_root/macro_identifier`，top=`macro_top`。

- 严格编译 0 error；
- `macro_signal` 不得 eligible；
- 必须存在一个 `signals/macro_signal/preserved/macro_expansion` entry；
- 不得为宏展开声明伪造指向宏 definition body 的 declaration range；
- top ports `value_i/value_o` 仍为 `preserved/top_port`。

## 10. 固定负向 fixtures

每条命令必须退出 1、生成 `status=error` 报告，并包含精确 primary code：

| Fixture | Top | Primary code |
| --- | --- | --- |
| `missing_top` | `not_present` | `TOP_NOT_FOUND` |
| `ambiguous_top` | `duplicate_top` | `AMBIGUOUS_TOP` |
| `missing_module` | `missing_module_top` | `UNRESOLVED_MODULE` |
| `ambiguous_definition` | `ambiguous_definition_top` | `AMBIGUOUS_DEFINITION` |
| `missing_include` | `missing_include_top` | `MISSING_INCLUDE` |
| `ambiguous_include` | `ambiguous_include_top` | `AMBIGUOUS_INCLUDE` |
| `unresolved_macro` | `unresolved_macro_top` | `UNRESOLVED_MACRO` |
| `ambiguous_macro` | `ambiguous_macro_top` | `AMBIGUOUS_MACRO` |

附加正例：

- `ambiguous_include` 加 `--include-dir dir_a` 后成功、compile error=0；
- `unresolved_macro` 加 `--define T027_MISSING_VALUE=4` 后成功、compile error=0；
- CLI define 必须记录在 `compile.defines`，不得虚构 source provider。

## 11. 固定 RISC-V-Vector 验收

输入：

```text
project-root = rtl_samples/RISC-V-Vector
top          = vector_top
```

该目录已在提交 `5586a30` 固定，上游版本记录在 `UPSTREAM.md`。子 Agent不得修改任何文件或
mode。验收命令不传 filelist、include-dir 或 define，以证明 `project-root + top` 默认模式有效。

精确预期：

- candidate files：56；
- reachable modules：17；
- reachable interfaces：0；
- closure files：19，精确集合如下：

```text
rtl/shared/and_or_mux.sv
rtl/shared/eb_buff_generic.sv
rtl/shared/eb_one_slot.sv
rtl/shared/fifo_duth.sv
rtl/vector/v_fp_alu.sv
rtl/vector/v_int_alu.sv
rtl/vector/vector_top.sv
rtl/vector/vex.sv
rtl/vector/vex_pipe.sv
rtl/vector/vis.sv
rtl/vector/vmacros.sv
rtl/vector/vmu.sv
rtl/vector/vmu_ld_eng.sv
rtl/vector/vmu_st_eng.sv
rtl/vector/vmu_tp_eng.sv
rtl/vector/vrat.sv
rtl/vector/vrf.sv
rtl/vector/vrrm.sv
rtl/vector/vstructs.sv
```

reachable module 精确集合：

```text
and_or_mux
eb_buff_generic
eb_one_slot
fifo_duth
v_fp_alu
v_int_alu
vector_top
vex
vex_pipe
vis
vmu
vmu_ld_eng
vmu_st_eng
vmu_tp_eng
vrat
vrf
vrrm
```

其他硬约束：

- `rtl/shared/params.sv` 不在 closure；
- `sva/*.sv` 不在 closure，因为默认未定义 `MODEL_TECH`；
- `vector_simulator/**` 不在 closure；
- parse errors = 0，semantic errors = 0；
- 所有 eligible range 位于上述 19 个文件；
- parameter 不进入 eligible inventory；
- 连续运行两次报告 bytes 相同；
- `git diff --exit-code 5586a30 -- rtl_samples/RISC-V-Vector` 必须成功。

T027 不冻结 RISC 工程五类对象的最终 entry/occurrence 总数；T029 在 T027/T028 接受后使用
最终 collector 生成并冻结 RISC inventory oracle。T027 已通过 integration fixture 精确检查
inventory 完整性，RISC 验收重点是通用发现、依赖闭包和严格 compilation。

## 12. 子 Agent 内部执行方案

### 阶段 A：开始和 API 探针

1. 按第 2 节更新任务状态并记录 HEAD。
2. 只读检查现有 `_build_project_inventory`、CLI 和 collector，不先重构。
3. 用最小 PySlang 探针确认并记录：
   - `SyntaxTree.fromFiles` 返回单个组合 SyntaxTree；
   - `SourceManager.addUserDirectories`；
   - `pyslang.parsing.PreprocessorOptions.predefines` 通过 `Bag` 传给 `SyntaxTree.fromFiles`；
   - `CompilationOptions.topModules`；
   - top instance、definition、source buffer 到文件路径的实际 API。
4. API 与合同不符时先写入“偏差或阻塞”，不得自行引入其他 parser。

阶段门禁：三个正向 fixture 的原始严格 compilation 均为 0 error。

### 阶段 B：发现、定义和预处理依赖

1. 实现候选文件发现和相对路径规范化。
2. 实现 definitions 索引和 top 唯一性。
3. 实现 include/macro provider、active 条件和结构化错误。
4. 先运行 discovery/preprocessor 对应测试；失败时不进入下一阶段。

阶段门禁：candidate/definitions、8 个负例、两个显式消歧正例全部匹配合同。

### 阶段 C：top 闭包和严格 compilation

1. 迭代构建 module/interface/type/include/macro closure。
2. 生成确定性 compile order。
3. 用共享 SourceManager、组合 SyntaxTree、topModules 严格编译闭包。
4. 明确选择 top 实例并导出 reachable module/interface tree。

阶段门禁：integration 为 3 modules/1 interface/6 files/0 errors；RISC 为
17 modules/0 interfaces/19 files/0 errors。

### 阶段 D：inventory、ranges 和报告

1. 复用现有 semantic collector，改为接受 selected top traversal boundary。
2. 补充 compilation-unit struct type/field scope。
3. 计算 top ABI 和宏展开 preserved reason。
4. 生成排序稳定的 report 和 stdout summary。

阶段门禁：integration 精确 32/107，top ABI 和 macro fixture 精确匹配，所有 range 回读、
无重复、无重叠、确定性检查通过。

### 阶段 E：完整交付

1. 运行第 14 节全部命令。
2. 检查第 15 节文件边界和 RISC 输入未变。
3. 填写第 17—19 节记录。
4. 只有全部通过时设置 `READY_FOR_REVIEW`。

## 13. 测试文件和固定测试数

新增 `tests/test_project_root_inspect.py`，必须正好包含以下 16 个 unittest：

```text
test_integration_discovery_definition_and_closure
test_integration_inventory_exact_oracle
test_integration_ranges_and_determinism
test_top_abi_is_preserved
test_macro_generated_identifier_is_preserved
test_missing_top_error
test_ambiguous_top_error
test_missing_module_error
test_ambiguous_definition_error
test_missing_include_error
test_ambiguous_include_error
test_unresolved_macro_error
test_ambiguous_macro_error
test_explicit_include_dir_resolves_ambiguity
test_command_line_define_resolves_macro
test_risc_v_vector_closure
```

测试必须调用公开 CLI 或公开 project analysis API；不得复制实现算法后让“实现与测试犯同一个
错误”。精确 symbol oracle 来自本合同表格，ranges 通过独立读取 fixture bytes 验证。

## 14. 固定验收命令

所有命令在仓库根目录执行。

### 14.1 语法和目标测试

```sh
conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project.py \
  rtl_obfuscator/inventory.py \
  rtl_obfuscator/rewrite.py \
  tests/test_project_root_inspect.py

conda run -n rtl_obfuscation python -m unittest \
  tests.test_project_root_inspect -v
```

固定结果：`Ran 16 tests`、`OK`。

### 14.2 integration CLI

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root tests/fixtures/t027_project_root/integration \
  --top project_top \
  --report /tmp/rtl_obfuscation_t027/integration.json
```

必须退出 0，stdout 精确匹配第 3.2 节，报告满足第 8 节。再次运行到
`/tmp/rtl_obfuscation_t027/integration-second.json` 后：

```sh
cmp /tmp/rtl_obfuscation_t027/integration.json \
  /tmp/rtl_obfuscation_t027/integration-second.json
```

必须退出 0。

### 14.3 RISC CLI

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root rtl_samples/RISC-V-Vector \
  --top vector_top \
  --report /tmp/rtl_obfuscation_t027/risc-v-vector.json
```

必须退出 0；第 11 节所有集合和 error count 由 unittest 与独立 JSON assertion 检查。

### 14.4 负向 CLI

每个第 10 节 fixture 都必须由 unittest 通过 subprocess 验证退出码、报告状态和 primary code；
不能只调用内部函数。两个消歧正例必须退出 0。

### 14.5 完整回归和边界

```sh
conda run -n rtl_obfuscation python -m unittest discover -s tests -v
git diff --exit-code 5586a30 -- rtl_samples/RISC-V-Vector
git diff --check
git status --short
```

固定完整回归：现有 33 项加新增 16 项，必须为 `Ran 49 tests`、`OK`。

`git status --short` 只允许第 15 节实现/测试文件和本任务执行记录发生变化；路线图和 README 的
主 Agent 规划变更可能在任务开始前已存在，不属于子 Agent 可修改文件，子 Agent不得覆盖、
回退或暂存它们。

## 15. 允许修改的文件

子 Agent只允许修改：

```text
rtl_obfuscator/project.py                 # 新文件
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
rtl_obfuscator/__init__.py                # 仅在导出公开 API 确有需要时
tests/test_project_root_inspect.py         # 新文件
docs/tasks/T027_project_root_top_analysis.md
```

以下固定输入只读，禁止修改内容、路径或 file mode：

```text
tests/fixtures/t027_project_root/**
rtl_samples/RISC-V-Vector/**
```

未经主 Agent 修订合同，不得修改其他测试、现有 fixtures、README、路线图、重命名表、formal
脚本或依赖配置。

## 16. 严格行为规范和禁止事项

1. 不得实现 T028 的加密、mapping v3、gate 输出或 decrypt。
2. 不得重命名 parameter，也不得把现有 `parameters` category 从旧 CLI 删除。
3. 不得为使 RISC 通过而编译全部工程后过滤 diagnostics；严格 compilation 必须是 19 文件闭包。
4. 不得吞掉、降级或按 message 文本忽略 PySlang error。
5. 不得把 unresolved module 当 blackbox 静默接受。
6. 不得按“第一个搜索结果”解决重复 top/module/include/macro。
7. 不得用纯正则替代 PySlang 的最终语义绑定。正则/词法扫描只可用于容错候选索引，最终
   closure、scope、identity 和 ranges 必须由严格 compilation 验证。
8. 不得伪造 source range、把宏 definition body 当作宏展开 identifier 的声明位置，或让
   ranges 指向 closure 外文件。
9. 不得从 compilation root 全局收集后仅按文件名过滤；inventory 必须从 selected top 实例树
   遍历。
10. 不得修改固定 fixture、RISC 样例、预期 32/107、17 modules 或 19 files 来制造通过。
11. 不得增加第三方依赖、联网下载 parser、使用系统/base 环境中的 EDA 工具。
12. 所有 Python、PySlang、Verible、Icarus、Yosys 或测试命令都通过
    `conda run -n rtl_obfuscation`；T027 不需要运行 Yosys。
13. 不得运行 identity formal 并把它写成 T027 正确性证据；formal 明确为 N/A。
14. 不得 commit、push、rebase、amend、reset 或删除用户已有变更。
15. 不得设置 `ACCEPTED`，不得创建 T028。
16. 如果需要修改允许列表、schema、错误码、fixture 或精确 oracle，必须先在“偏差或阻塞”中
    记录并停止，等待主 Agent 修订合同。

## 17. 子 Agent 执行记录

```text
start_time: 2026-07-16 17:39:58 CST
starting_head: 1dcebb4
first_command: `sed -n '1,260p' AGENTS.md; sed -n '1,260p' docs/tasks/README.md; rg -n '^# T027|^- 状态：|^## ' docs/tasks/T027*.md docs/tasks/*.md; sed -n '1,420p' docs/tasks/T027*.md; git status --short --branch; git rev-parse --short HEAD`
confirmed_unique_active_task: yes; T027 is the only `READY` task and no task is `IN_PROGRESS` or `READY_FOR_REVIEW`
pyslang_api_probe: PySlang 11.0.0 confirmed `SyntaxTree.fromFiles(paths, SourceManager, Bag)` returns one `CompilationUnitSyntax`; `SourceManager.addUserDirectories(path)` accepts one directory per call; `PreprocessorOptions.predefines` is a list assigned through `Bag.preprocessorOptions`; `CompilationOptions.topModules` is a set assigned through `Bag.compilationOptions`; `RootSymbol.topInstances` provides the selected `InstanceSymbol`, whose `definition`, `body`, `location`, and source buffer resolve through `Compilation.sourceManager.getFullPath()`.
phase_a_gate: integration, top_abi, macro_identifier, and the fixed 19-file RISC closure each compiled with one shared SourceManager / combined SyntaxTree / compilation unit, exactly one requested top instance, and 0 parse / semantic errors.
phase_b_gate: candidate and definition indexes matched the frozen fixtures; all eight negative CLI cases returned exit 1 with the required primary code; explicit include-dir and command-line define disambiguation returned exit 0 with 0 compilation errors.
phase_c_gate: integration reached exactly 3 modules / 1 interface / 6 files and RISC reached exactly 17 modules / 0 interfaces / 19 files; both strict closure compilations reported 0 parse and 0 semantic errors.
phase_d_gate: integration inventory matched exactly 32 entries / 107 occurrences; top ABI matched the exact 8 preserved entries; macro-generated `macro_signal` was preserved with `declaration=null`; every emitted physical range was source-validated and deterministic.
finish_time: 2026-07-16 18:03:15 CST
```

## 18. 偏差或阻塞

None.

不得在本节记录问题后仍自行扩大实现范围。

## 19. READY_FOR_REVIEW 交付证据

```text
changed_files: rtl_obfuscator/project.py (new); rtl_obfuscator/inventory.py; rtl_obfuscator/rewrite.py; tests/test_project_root_inspect.py (new); docs/tasks/T027_project_root_top_analysis.md
exact_commands: `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project.py rtl_obfuscator/inventory.py rtl_obfuscator/rewrite.py tests/test_project_root_inspect.py`; `conda run -n rtl_obfuscation python -m unittest tests.test_project_root_inspect -v`; both fixed integration CLI commands followed by `cmp`; fixed RISC CLI command; `conda run -n rtl_obfuscation python -m unittest discover -s tests -v`; `git diff --exit-code 5586a30 -- rtl_samples/RISC-V-Vector`; `git diff --check`; `git status --short`
exit_codes: all positive, py_compile, unittest, cmp, RISC immutability, and diff-check commands exited 0; each of the eight fixed negative CLI cases exited 1; invalid top and outside-root include-dir probes exited 2
integration_stdout: `{"candidate_files":7,"closure_files":6,"definitions":6,"eligible_occurrences":107,"eligible_symbols":32,"reachable_interfaces":1,"reachable_modules":3,"status":"pass","top":"project_top"}`
integration_report_summary: 7 candidates; 6 definitions; 6 closure files; 3 reachable modules; 1 reachable interface; exact source compile order `internal_if.sv, structs.sv, leaf.sv, child.sv, top_bundle.sv`; 0 parse errors; 0 semantic errors; 32 eligible symbols / 107 occurrences
negative_fixture_results: missing_top/TOP_NOT_FOUND; ambiguous_top/AMBIGUOUS_TOP; missing_module/UNRESOLVED_MODULE; ambiguous_definition/AMBIGUOUS_DEFINITION; missing_include/MISSING_INCLUDE; ambiguous_include/AMBIGUOUS_INCLUDE; unresolved_macro/UNRESOLVED_MACRO; ambiguous_macro/AMBIGUOUS_MACRO; all exit 1 with one primary diagnostic
risc_report_summary: 56 candidates; 38 definitions; exact 17 reachable modules; 0 interfaces; exact 19 closure files; 0 parse errors; 0 semantic errors; `params.sv`, `sva/**`, and `vector_simulator/**` excluded
range_oracle_result: PASS; every definition and inventory declaration/reference range read back as its exact UTF-8 identifier; no duplicate or overlapping inventory ranges; macro-generated declaration remained null
determinism_result: PASS; integration and RISC repeated stdout and report bytes matched exactly; fixed integration `cmp` exited 0
target_unittest_result: `Ran 16 tests in 8.756s`; `OK`
full_unittest_result: `Ran 49 tests in 17.944s`; `OK`
risc_immutability_result: `git diff --exit-code 5586a30 -- rtl_samples/RISC-V-Vector` exited 0
git_diff_check: exit 0; status contains only the five files allowed by section 15
formal_verification: N/A
formal_reason: no rewritten RTL is produced by T027
uncovered_boundaries: no behavior beyond the contract was added; macro-generated definitions remain `UNSUPPORTED_MACRO_IDENTIFIER`, and T028 rewrite/mapping/gate behavior remains out of scope
```

## 20. 主 Agent 独立验收

主 Agent 不依赖人工阅读实现代码判定通过，必须独立执行：

1. 第 14.1 节 py_compile 和 16 项目标 unittest；
2. integration CLI 两次及 `cmp`；
3. 八个负向 subprocess 和两个显式消歧正例；
4. top ABI、macro identifier 的 exact preserved 集合；
5. RISC CLI 的 56 candidates、17 modules、19 files、0 errors；
6. 对每个 eligible declaration/reference range 独立读取 bytes，检查精确原名、无重复和无重叠；
7. 完整 49 项 unittest；
8. RISC 输入相对 `5586a30` 无变化；
9. `git diff --check` 和允许文件审计。

只有全部通过时，主 Agent 才能把本任务设置为 `ACCEPTED`。任一闭包集合、error count、oracle、
确定性或 legacy 回归不符，都必须退回 `IN_PROGRESS`；不能以“RISC 很大”或“T028 会处理”为由
接受部分实现。

### 主 Agent 验收结果

- `ACCEPTED`（2026-07-16，主 Agent 独立验收）。
- `py_compile` 退出码 0；16 项目标 unittest 在 8.694 秒内全部通过。
- 主 Agent 独立执行两次 integration、两次 RISC、top ABI 和 macro CLI；integration stdout
  精确为合同固定值，两组重复报告均逐字节一致。
- 独立 JSON/range 审计通过：integration 为 32 symbols / 107 occurrences，验证 126 个物理
  range；top ABI 精确 8 个 preserved 对象；macro declaration 为 null；RISC 为 56 candidates、
  17 modules、19 closure files、1085 eligible symbols、5529 个物理 range，且 0 parse/
  semantic error。
- 八个负向 CLI 分别返回合同固定 primary code 和退出码 1；显式 include-dir、command-line
  define 两个消歧正例退出码 0，define 未虚构 source provider。
- 完整回归为 `Ran 49 tests in 17.856s`、`OK`。
- `rtl_samples/RISC-V-Vector` 相对 `5586a30` 无变化；T027 固定 fixtures 相对 `1dcebb4`
  无变化；允许文件审计和 `git diff --check` 通过。
- Formal verification：`N/A`，本任务没有产生重写 RTL；未运行 identity formal。
