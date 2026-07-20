# SystemVerilog 重命名表

本表只描述当前代码已经实现并通过回归的 category。所有收集都以 PySlang compilation
能够解析并确认语义绑定为前提；边界外语法不应仅凭加密命令退出码判断为可用。

## 0. 当前工作流 profile

同一 category 表在不同入口中的默认集合不同，不能把 `all`、filelist 和
`project-root + top` 视为同义：

| 工作流 | 普通模式默认 | 普通模式手动选择 | debug |
| --- | --- | --- | --- |
| 单文件 | 必须传一个 category；可传 `all` | 13 个非 ABI 底层 category | 13 个 category |
| 显式 filelist 多文件 | 必须传 `--category` | 19 个底层 category；`all` 展开 13 类，6 个 ABI 类需显式追加 | 19 个 category |
| `project-root + top` | `signals`、`ports`、`instances`、`struct`、`interface` 五组 | 共 14 个用户组，另含 `enum_values`、`genvars`、`functions`、`tasks`、`arguments`、`generate_blocks`、`typedefs`、`union_fields`、`parameters` | 13 个非-parameter 用户组；当前不遍历 `parameters` |

project-root 的 `struct` 展开为 `struct_types + struct_fields`，`interface` 展开为
`interfaces + interface_instances + interface_ports + modports`；project-root 不接受
`all` 或底层 category 名。`parameters` 已支持显式 inventory/rewrite，但尚未进入
project-root 默认 profile，也尚未进入 project-root debug。

## 1. `all` 默认启用的类别

| Category | 当前重命名对象 | 必须同步修改 | 支持示例 | 主要边界 | FIFO entries/tokens |
| --- | --- | --- | --- | --- | ---: |
| `signals` | module 内部、非 port 的 variable/net | 声明、读写、select 和表达式引用 | `logic count; assign q=count;` | 不含 port、argument、interface member、field | 14/67 |
| `parameters` | module value parameter、普通 module localparam | 声明、表达式、dimension、generate header、named override 左侧 | `parameter W=8; logic [W-1:0] d;` | 不含 type/package/class/interface parameter、`defparam`、任意复杂遮蔽 | 9/51 |
| `enum_values` | module enum member | 声明、赋值、比较和 case 引用 | `enum {IDLE,BUSY}; s=IDLE;` | 不含 package/class enum | 3/6 |
| `genvars` | generate-for genvar | 声明、条件、步进和 body 引用 | `for (genvar i=0; i<N; i++)` | 不保证任意嵌套 generate 和外部层次引用 | 2/10 |
| `functions` | module function 名 | 声明、普通调用和已绑定的函数返回变量引用 | `function f(...); q=f(d);` | 不含 extern、DPI、package/class function | 2/7 |
| `tasks` | module task 名 | 声明和普通调用 | `task clear(...); clear(q);` | 不含 extern、DPI、层次调用 | 1/2 |
| `arguments` | module function/task 形式参数 | 声明和 subroutine 内引用 | `function f(input logic value);` | 不含 prototype 和命名实参左侧 | 4/9 |
| `instances` | 具名 module instance | instance 声明 | `child u_child(...);` | 不改外部层次路径、instance array、primitive/checker | 2/2 |
| `generate_blocks` | 显式 generate block label | label 声明 | `begin : g_lane` | 不改隐式 `genblkN` 和外部层次路径 | 2/2 |
| `typedefs` | module 普通 typedef 名 | 声明和已支持的类型引用 | `typedef logic [7:0] word_t;` | 不含 package/class typedef、全部 cast/prototype | 2/7 |
| `struct_types` | module 或 compilation-unit typedef struct/union 类型名 | 声明和已支持的类型引用 | `typedef struct {...} item_t;` | 不含 package/class scope 和任意嵌套组合 | 2/5 |
| `struct_fields` | struct field | 声明和已绑定 member access | `item.valid` | 不含 pattern key、constraint、反射/DPI 依赖 | 2/4 |
| `union_fields` | union field | 声明和已绑定 member access | `view.raw` | 不含 tagged union、pattern key、constraint | 2/6 |

`--category all` 只展开以上 13 类。

## 2. 必须显式启用的 ABI 类别

| Category | 当前重命名对象 | 必须同步修改 | 支持示例 | 主要边界 | FIFO entries/tokens |
| --- | --- | --- | --- | --- | ---: |
| `modules` | 非 top module 定义 | module 声明和 instance type | `module child; child u();` | top module 始终保留；不处理 bind/config | 2/4 |
| `ports` | 非 top module 普通 port | 声明、module body、named connection 左侧、已绑定 aggregate base 和 generate actual | `child u(.data(x));` | top 普通 ports 始终保留；不处理外部约束 | 17/59 |
| `interfaces` | 工程内部 interface 定义 | 声明和已支持的 instance type | `interface bus_if; bus_if bus();` | 不支持顶层 interface port、virtual interface、package/config | 1/2 |
| `interface_instances` | 工程内部 interface instance | 声明和已支持的 member/connection 引用 | `bus_if fifo_bus(); fifo_bus.valid` | 不处理外部层次和 virtual interface 赋值 | 1/15 |
| `interface_ports` | 内部 interface port/member | 声明、member access、named connection、modport member | `logic valid; bus.valid` | 不支持顶层 interface port member、clocking 和复杂 import/export | 9/39 |
| `modports` | modport 声明名 | 当前仅声明 | `modport producer(...);` | 若 `.producer` 被实际引用则不要启用；完整引用改写尚未实现 | 2/2 |

这些类别可能改变 RTL 与 testbench、约束或其他模块之间的名称 ABI，因此不会被 `all`
隐式启用。`modport_ports` 不是独立 category；modport 列表中的 interface signal 归入
`interface_ports`。

## 3. 同名与遮蔽规则

同名文本不等于同一对象。下面的左右 `WIDTH` 必须分别绑定到 child 和调用方：

```systemverilog
child #(.WIDTH(WIDTH)) u_child (...);
```

当前已经验证：

- 不同 module 中同名的 value parameter 会生成不同 mapping entry；
- module parameter 与 generate-local genvar 同名时，不会把 genvar 引用误收为 parameter；
- 不同 struct/union 类型中的同名 field 不会合并；
- ANSI port 的底层 variable/net 不会再次作为 `signals` 重复重命名。

尚未保证：

```systemverilog
module m #(parameter WIDTH=8);
    typedef struct packed {
        logic [WIDTH-1:0] WIDTH;
    } item_t;
endmodule
```

这里 dimension 的 `WIDTH` 绑定外层 parameter，而 field 也叫 `WIDTH`。当前 aggregate
fallback 无法对所有这种声明位置遮蔽做可靠证明，应改用不同 field 名。

## 4. 全局输入边界

- 加密输入可以是显式 filelist，也可以由 `project-root + top` 自动建立已验收子集的 active
  include/宏闭包。project-root 默认只选择五个概念组，但普通模式已开放 14 个用户组，
  包括显式 `parameters`；`modules` 仍不属于 project-root 用户组，`all` 也不适用。
- project-root collector 对 `syntax is None` 的 port `NamedValueExpression` 只在
  `symbol is port.internalSymbol` 成立后使用精确 source range；未展开 generate actual 只在 lexical
  lookup 返回同一父模块 port internal symbol 时收集。RISC-V-Vector 固定结果为 1091/5741。
- compilation-unit packed struct 的单层 packed-array element alias 已支持；unpacked、嵌套或多层
  aggregate wrapper 仍不在重命名/formal-view 边界内。
- 只修改输入 RTL，不同步修改 testbench、SDC、Tcl、软件模型和外部层次路径。
- 不支持 type parameter、package/class/interface/$unit parameter、parameter array/string/real/struct、
  `defparam`、DPI、bind、class、clocking block、virtual interface 和任意完整 SystemVerilog
  lexical shadow。
- 顶层使用 `interface.modport` port 时，应保留整个 interface ABI；当前不能只保留 top port
  名而安全加密 interface 类型、modport 和 member。
- 详细待办见 [future_work.md](future_work.md)。
