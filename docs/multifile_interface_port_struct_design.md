# 多文件、port、interface 与 struct 重命名设计

## 1. 当前结论

当前实现能够对一个 SystemVerilog 文件中的 7 个已验收 category 执行一次全量重命名：

```text
signals parameters enum_values genvars functions tasks arguments
```

它不是“单文件全部名称类型”。`docs/systemverilog_renaming_table.md` 中仍未实现的类别包括：

```text
modules type_parameters ports instances generate_blocks
interfaces interface_instances interface_ports modports modport_ports
typedefs struct_types struct_fields union_fields
```

其中 `instances`、`generate_blocks`、type/field 类别可以先在单文件 Compilation 中实现；module、port 和 interface 的完整同步修改天然涉及定义与使用点，必须建立多文件 Compilation 后再作为正式能力交付。

## 2. 当前单文件架构不能直接扩展到多文件的原因

当前实现具有以下硬边界：

- rewrite CLI 只有一个 `--input` 和一个 `--output`。
- inventory 只从一个 `SyntaxTree.fromFile()` 建立 Compilation。
- `_range_record` 要求所有 declaration/reference 都位于同一个 input file。
- source edits 只对一个 bytes buffer 排序和应用。
- stdout 固定报告 `files=1`。
- decrypt 只重新解析一个 gate 文件。
- formal 脚本只接受一个 gold 和一个 gate。

因此，多文件支持不能通过对多个文件逐个调用现有 CLI 实现。逐文件解析会丢失 module/port/interface/type 的跨文件 symbol binding，并可能只改声明或只改部分引用。

## 3. 推荐的项目级流水线

内部只保留一条项目流水线；单文件是 `files=[one_file]` 的特例：

```text
显式输入清单
  → 一次建立包含所有 SyntaxTree 的 PySlang Compilation
  → 全局收集 targets 和已有 identifiers
  → 建立语义所有权并去除 alias/重复对象
  → 全局生成唯一名称
  → 收集跨文件 declaration/reference ranges
  → 按文件分组、校验和倒序应用 edits
  → 写入镜像输出目录
  → 全项目前端检查、formal、单 mapping 恢复
```

不得在内部为每个文件复制或循环调用当前单文件 rewrite 命令。

### 3.1 建议 CLI

保留当前单文件 `encrypt/decrypt` 作为小样例和 debug 入口；增加项目级适配层，但复用同一内部 pipeline：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist design.f \
  --source-root . \
  --output-dir /tmp/gate \
  --map /tmp/gate/mapping.json \
  --metrics /tmp/gate/metrics.json \
  --top top_module \
  --category all \
  --name-length 8
```

第一版 filelist 只允许：UTF-8、每个非空行一个相对 source-root 的 `.sv` 路径。暂不解析 `+incdir+`、`+define+`、library 或嵌套 filelist。

项目级 `--category` 应允许重复。`all` 只展开重命名表中默认启用且已经验收的安全类别；`modules`、`ports`、`interfaces`、`interface_ports`、`modports`、`modport_ports` 等 ABI 类别不得被 `all` 静默启用，必须显式写出。例如：

```sh
--category all --category ports
```

即使显式启用 `modules/ports`，第一版仍强制 preserve top module 及其 ports。

输出目录保持输入相对路径：

```text
src/pkg/types.sv  → /tmp/gate/src/pkg/types.sv
src/rtl/child.sv  → /tmp/gate/src/rtl/child.sv
src/rtl/top.sv    → /tmp/gate/src/rtl/top.sv
```

### 3.2 项目 mapping

多文件 mapping 应使用一个明确的新 schema，不给 v1 增加可选字段：

```json
{
  "version": 2,
  "name_length": 8,
  "files": [
    "src/pkg/types.sv",
    "src/rtl/child.sv",
    "src/rtl/top.sv"
  ],
  "entries": []
}
```

每个 range 的 `file` 必须是相对 source-root 的规范路径；references 可以位于多个文件。`decrypt-project` 只接受 v2，现有单文件 decrypt 继续只接受 v1，不增加猜测或自动转换。

### 3.3 edits 与写出规则

- 全部名称在整个 Compilation 中共享一个 unavailable/new-name 集合。
- mapping 按 `declaration.file、declaration.start、category` 稳定排序。
- 重复和重叠 range 按“同一个语义所有者”协调；不同所有者命中同一 range 直接失败。
- 所有文件的 ranges、expected bytes 和输出语义先验证完成，再写任何 gate 文件。
- 未发生改写的输入文件也必须复制到输出树，保证 gate filelist 完整。
- decrypt 使用 mapping v2 的 files 和 entries 一次恢复整个目录，并逐文件字节比较。

### 3.4 全局 metrics

- affected lines：所有输入文件的变更行数之和 / 所有输入文件有效代码行数之和。
- symbols 和 occurrences：全项目聚合。
- plaintext leakage 必须升级为 SystemVerilog identifier token 统计，不能继续使用原始 byte substring 计数。
- metrics 仍只描述 gold 到最终 gate；formal 是独立正确性门禁。

## 4. module 与 port 设计

### 4.1 module

- canonical target 是 module definition symbol。
- 同一 entry 包含 module 声明和所有已绑定 instance type 引用。
- 第一版始终保留 `--top` 指定的顶层 module 名；只允许重命名完整输入项目内部的非 top module。
- unresolved/external module、bind/config 或未输入的引用直接判定为范围外，不做文本猜测。

### 4.2 port

一个 ANSI port 可能同时存在 `PortSymbol` 和底层 `VariableSymbol/NetSymbol`。它们必须折叠成一个 canonical port target：

```text
port declaration
  + module 内部绑定到底层 internalSymbol 的引用
  + 所有 instance named connection 左侧 .port_name(...)
```

关键所有权规则：

- `.data_i(data_i)` 左侧属于被实例化 module 的 port；右侧属于调用 module 的 signal/port，两个 token 不能按字符串合并。
- positional connection 没有被调用 port 名 token，不产生 port edit。
- 第一版保留 top module 的全部 ports；只重命名非 top、且所有实例化都位于项目输入内的 child ports。
- 若需要修改 top ports，必须另行设计 formal wrapper 和外部 ABI 更新，不在第一版 port 任务中实现。

## 5. struct、union 和 typedef 设计

这些类别先在单文件实现语义 collector，再由项目 Compilation 自然扩展到跨文件 type references。

### 5.1 类型名称所有权

必须避免一个 typedef struct 名同时生成 `typedefs` 和 `struct_types` 两个 entry：

- `typedef logic [7:0] byte_t;`：归 `typedefs`。
- `typedef struct/union ... header_t;`：归 `struct_types`。
- type parameter：归 `type_parameters`。

类型引用不能使用 NamedValueExpression collector；需要依据 PySlang type symbol 和对应 type syntax 收集变量、port、parameter、cast、function 签名等位置。

### 5.2 field 所有权

- packed/unpacked struct member 归 `struct_fields`。
- union member 归 `union_fields`。
- SymbolKey 必须包含 owner type identity 或 owner type declaration range；不同类型中同名 field 不能合并。
- declaration、普通 member access、assignment pattern key 必须绑定同一 field symbol 后才允许改写。
- 如果当前 PySlang API 无法为 assignment pattern key 提供可靠 binding，该 field 不得标为完整支持；先记录 BLOCKED，而不是字符串搜索。

字段改名不改变 bit layout，但每个 rewritten fixture 仍必须通过 Yosys formal。

## 6. interface 与 modport 设计

interface 应建立在多文件 Compilation、module port 和 type reference collector 之后。

### 6.1 canonical ownership

| 源码实体 | canonical category |
| --- | --- |
| interface 定义名和 interface type 引用 | `interfaces` |
| 独立 interface instance 名 | `interface_instances` |
| module 中 interface-typed port 的 port 名 | `ports` |
| interface 内部 signal/port member | `interface_ports` |
| modport 名 | `modports` |
| modport 列表对已有 interface member 的引用 | 归对应 `interface_ports` entry 的 reference |

`modport_ports` 只有在 PySlang 暴露“与底层 interface member 不同的独立 alias/import/export symbol”时才生成独立 entry；普通 `modport master(output valid)` 中的 `valid` 不得与 `interface_ports/valid` 重复映射。

### 6.2 实施边界

- `interfaces`、`interface_ports`、`modports` 默认不加入安全的 `all` 集合；必须显式启用。
- 第一版只处理项目内完整可解析的静态 interface instance 和 module interface port。
- virtual interface、class、clocking block、DPI、bind 和外部 testbench 层次引用暂不处理。
- interface 定义、实例、member access、modport type 和 modport list 必须在同一 Compilation 内协调。

## 7. 多文件 formal

扩展 formal 脚本接受 gold filelist、gate root 和保持不变的 top：

```text
read_verilog -sv -formal <all gold files>
prep -top <top> -flatten
...
read_verilog -sv -formal <all mirrored gate files>
prep -top <top> -flatten
...
equiv_status -assert
```

第一版通过保留 top module 和 top ports，使 gold/gate 可以直接构建 equivalence。每个项目级任务还必须分别运行 PySlang、Verible 和 Icarus 的完整 filelist 检查。

## 8. 推荐实施顺序

| 任务 | 内容 | 主要复用 |
| --- | --- | --- |
| T012 | 单文件 `instances`、`generate_blocks` | hierarchy/source-range、现有 one-pass all |
| T013 | 单文件 `type_parameters`、`typedefs`、`struct_types` | type symbol/reference collector |
| T014 | 单文件 `struct_fields`、`union_fields` | owner type identity、member access |
| T015 | 多文件基础设施，只对现有已验收 category 做跨文件回归 | Compilation、per-file edits、mapping v2、project formal |
| T016 | 多文件非 top `modules`、child `ports` | definition-instance binding、named connection |
| T017 | `interfaces`、`interface_instances` | interface type/instance binding |
| T018 | `interface_ports`、`modports`、`modport_ports` | canonical member ownership |
| T019 | 全类别组合、默认/显式 ABI category、完整项目回归 | 全部现有 pipeline |

每个任务仍应保持一个最小 fixture 集和一个唯一 `READY` 合同；不能在 T015 尚未验收前实现正式的跨文件 port/interface 重命名。

## 9. 项目级验收标准

开发者不需要深入代码，只检查：

1. 固定 filelist、source-root、top、categories 和 name length。
2. mapping v2 的 files、entry 数、跨文件 declaration/reference ranges。
3. 每个 gate 文件只包含 mapping 描述的 edits；未改文件字节不变。
4. 全项目 PySlang、Verible、Icarus 通过。
5. 多文件 Yosys formal PASS。
6. `decrypt-project` 后目录树与 gold 逐文件字节一致。
7. 明确列出 top/ABI preserve 项、外部引用和未覆盖语法。
