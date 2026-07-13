# SystemVerilog 重命名表

本表汇总当前计划支持的 SystemVerilog 重命名项目，不区分实现阶段。建议默认值以“在 compilation 完整、符号可以正确解析、相关声明也位于允许修改的源文件中”为前提。

| 重命名项类型 | 可替换实体 | **SystemVerilog 示例** | **必须同步修改的位置** | **建议默认值** |
| --- | --- | --- | --- | --- |
| `modules` | module 定义名 | `module fifo (...);` 中的 `fifo` | module 声明；所有实例化处的模块类型名 `fifo u_fifo`；`bind` 目标；package/config 中对该 module 的引用；可解析的层次或作用域引用 | `false`。module 名通常是构建脚本、testbench 或综合流程使用的外部入口 |
| `parameters` | value parameter、`localparam` | `parameter int WIDTH = 8`、`localparam int DEPTH = 16` | 声明；所有表达式引用；命名参数覆盖左侧 `.WIDTH(...)`；层次引用和 `defparam`（若支持） | `true`。顶层公开 parameter 建议通过 preserve 规则排除 |
| `type_parameters` | type parameter | `parameter type T = logic [7:0]` 中的 `T` | 声明；所有类型引用；命名参数覆盖左侧 `.T(...)`；作用域和层次引用 | `true`。公开 module/interface 的 type parameter 可保留 |
| `ports` | module 的 input/output/inout/ref port | `input logic data_i` 中的 `data_i` | port 声明；模块内部引用；所有实例化处命名端口连接左侧 `.data_i(...)`；层次引用 | `false`。port 通常属于外部接口 ABI |
| `signals` | module 作用域内、非 port 的具名 variable 和 net | `logic masked_data;`、`reg stored_data;`、`wire ready;`、`tri shared_bus;` | 声明；驱动、赋值和读取；bit/part select；数组索引；连续或过程赋值；层次引用；alias 或连接表达式 | `true`。公开选项统一为 `signals`；实现内部同时收集 PySlang `VariableSymbol` 和 `NetSymbol` |
| `functions` | function 名 | `function automatic logic calc_crc(...);` 中的 `calc_crc` | 声明；所有函数调用；作用域引用 `pkg::calc_crc`；对象或层次引用；function prototype/extern 定义对应关系 | `true`。DPI、export、extern 或工具脚本依赖的 function 应保留 |
| `tasks` | task 名 | `task automatic drive_bus(...);` 中的 `drive_bus` | 声明；所有 task 调用；作用域或层次引用；task prototype/extern 定义对应关系 | `true`。DPI、export、extern 或验证环境公开 task 应保留 |
| `arguments` | function/task 形式参数 | `function f(input logic value);` 中的 `value` | 形式参数声明；subroutine 内所有引用；命名实参连接左侧 `.value(...)`；prototype 与实现中的对应声明 | `true` |
| `instances` | module、checker、primitive instance 名 | `child u_child (...);` 中的 `u_child` | instance 声明；所有层次路径，如 `u_child.ready`；`bind`、`disable`、force/release 等对该层次的引用 | `true`。外部 testbench、Tcl、SDC 或波形脚本引用的 instance 应保留 |
| `genvars` | generate 循环中的 `genvar` | `for (genvar lane = 0; ...)` 中的 `lane` | 声明；generate 条件、步进和循环体中的全部引用；相关索引表达式 | `true` |
| `generate_blocks` | 显式 generate block label | `begin : g_lane` 中的 `g_lane` | label 声明；所有层次路径，如 `g_lane[0].ready`；跨 module/testbench 的层次引用 | `true`。存在外部层次引用时建议保留；隐式 `genblkN` 不属于普通重命名 |
| `enum_values` | enum 枚举成员 | `typedef enum { IDLE, BUSY } state_t;` 中的 `IDLE`、`BUSY` | 枚举成员声明；赋值、比较和 case item；作用域引用 `state_t::IDLE`；assignment pattern 或 assertion 中的引用 | `true` |
| `interfaces` | interface 定义名 | `interface axi_if (...);` 中的 `axi_if` | interface 声明；所有 interface instance 的类型名；module/interface port 的 interface 类型；virtual interface 类型；作用域引用；`bind` 或 config 中的引用 | `false`。interface 通常是跨模块或验证环境的公开接口 |
| `interface_instances` | interface instance 名 | `axi_if bus_if (...);` 中的 `bus_if` | instance 声明；module port 连接表达式；所有层次引用，如 `bus_if.valid`；virtual interface 赋值；testbench 中的引用 | `true`。外部 testbench 或脚本按层次访问时应保留 |
| `interface_ports` | interface 内声明的 signal/port | `logic valid;`、`input logic clk;` 中的 `valid`、`clk` | interface 内声明和引用；modport 列表；clocking block；module 通过 interface port 访问的 member，如 `bus.valid`；层次引用 | `false`。它们往往构成 interface 的公开 ABI；封闭设计中可显式开启 |
| `modports` | modport 名 | `modport master (...);` 中的 `master` | modport 声明；module/interface port 类型中的 `.master`；virtual interface 类型；作用域或层次引用 | `false`。modport 名通常属于 interface 的公开类型接口 |
| `modport_ports` | modport 列出的 port 名或重命名项 | `modport master(output valid, input ready);` 中的 `valid`、`ready` | interface signal 声明及引用；modport 列表；通过该 modport 的 member access；import/export task/function 项 | `false`。应与对应的 interface signal 或 subroutine 作为同一语义对象协调重命名 |
| `typedefs` | typedef 定义的用户类型名 | `typedef logic [7:0] byte_t;` 中的 `byte_t` | typedef 声明；变量、port、parameter、cast、function 返回值及参数中的全部类型引用；作用域引用 `pkg::byte_t` | `true`。跨文件公开 package/interface 类型建议保留或使用 allowlist |
| `struct_types` | 命名 struct/union 类型，通常由 typedef 引入 | `typedef struct packed {...} header_t;` 中的 `header_t` | 类型声明；所有变量、port、参数、函数签名、cast 和嵌套类型中的引用；package/class 作用域引用 | `true`。公开协议数据类型建议默认保留或单独 preserve |
| `struct_fields` | packed/unpacked struct member | `logic [7:0] opcode;` 中的 `opcode` | member 声明；所有 member access，如 `header.opcode`；assignment pattern key，如 `'{opcode: value}`；with/inside/assertion/constraint 中的字段引用 | `true`。与 DPI、寄存器模型、序列化或工具脚本共享布局/字段名时应保留 |
| `union_fields` | packed/unpacked union member | `logic [31:0] word;` 中的 `word` | member 声明；所有 member access；tagged union 构造/匹配；assignment pattern key；assertion/constraint 中的引用 | `true`。与外部模型或字符串化反射机制共享字段名时应保留 |

## 使用说明

- “同步修改”必须依据 PySlang 的符号绑定关系完成，不能对同名字符串做全局替换。
- `logic` 是数据类型，不直接决定对象是 net 还是 variable；重命名器必须依据 PySlang 语义 symbol kind，而不是依据 `logic`、`reg`、`wire`、`tri` 关键字做文本分类。
- `signals` 第一阶段只包含 module 作用域内的内部 `VariableSymbol` 和 `NetSymbol`。module port、function/task argument、parameter、genvar、interface member 和 struct/union field 仍属于各自独立类别。
- 命名参数和命名端口连接的左右两侧可能文本相同，但分别属于被实例化单元和当前作用域中的不同符号。例如 `.WIDTH(WIDTH)` 左右两个 `WIDTH` 不一定应得到同一个新名字。
- ANSI port 在 PySlang 语义 AST 中可能同时表现为 `PortSymbol` 和底层的 `VariableSymbol`/`NetSymbol`。它们应作为同一个源码声明协调处理，不能生成两次重命名。
- interface signal、modport port 和普通变量可能指向同一底层语义对象；应用配置时应先解析对象关系，再决定最终名字。
- generate-for elaboration 可能产生多个 `GenerateBlock` 和迭代 parameter，但源码通常只有一个 label 和一个 `genvar` token。source edit 必须按源文件字节区间去重。
- struct/union 的成员名属于类型作用域，不应因为不同类型中存在同名字段就合并为同一个重命名对象。
- 只重命名声明和所有引用都能完整解析、且相关源码都允许修改的符号。未解析符号、DPI ABI、宏、工具 attribute、隐式 `genblkN` 和外部层次路径应默认保留。
