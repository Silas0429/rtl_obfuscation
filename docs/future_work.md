# 未来扩展与已知问题

> 2026-07-22 已确认新的优先方向：停止继续扩展历史 default/manual profile 与 mapping
> v2/v3/v4 兼容路径，按 [`docs/three_mode_refactor_plan.md`](three_mode_refactor_plan.md)
> 顺序建立 SourceSet、SymbolGraph 和统一 rewrite/audit/decrypt 流水线。T038 仍保留为
> `BLOCKED / NOT_ACCEPTED` 历史停点，重构任务尚未开始。

本文件只记录当前交付范围之外的事项。已经实现的功能和使用方法见根目录
[`README.md`](../README.md)，不要在本文件复制使用说明。

当前状态校准：T030 已交付低风险 category；T031/T032 已交付 module value
parameter/localparam inventory 和 rewrite；T035 已统一两种多文件入口的 13 类 default profile
和 19 类 manual profile。filelist manual profile 已在显式 filelist 内建立 bounded closure，
旧 v1/v2/v3 mapping 继续只读解密兼容，manual workflow 使用 mapping v4；T035 实现与非 RISC
回归已完成并验收。T036 已实现按唯一物理行目标选择 mapping、报告实际率并兼容三种入口；
T037 已完成 RISC-V-Vector Formal 专项验收和 `encrypt.py` 演示脚本；T038 当前修复
RISC-V-Vector 手动 parameter/genvar 边界，并统一加密率 metrics 的 effective-line 分母。
截至 2026-07-22，T038 仍为 `BLOCKED / NOT_ACCEPTED`：六组 RISC profile 的 gate/decrypt 实测为
`1211 entries / 6882 occurrences`，与合同冻结的 `6835` occurrences 不一致；紧凑 fixture、
专用验收脚本和 RISC Formal 正负例尚未交付。因此这部分不能计入已验收能力，也不能提前晋级
default profile。

## 1. 优先解决的问题

### 1.1 顶层 interface port ABI

当前不能可靠处理：

```systemverilog
module top(bus_if.slave bus);
    assign observed = bus.data;
endmodule
```

保留 top port 名 `bus` 并不足够；`bus_if`、`slave` 和 `data` 都属于顶层 ABI。当前
`project-root + top` inventory 已能识别这类 top ABI，并将 interface definition、modport、member
和 top port 放入 `preserved`，因此不会把它们误加入 project-root 的 eligible mapping。剩余问题是
尚未支持对这类 ABI 做安全的重命名；当前 Icarus/Yosys 对该语法的前端支持也不足，Yosys 可能把
`bus.data` 当作隐式信号，导致 formal 证明失去意义。

当前规避方式：两种多文件模式依靠 top ABI 闭包自动保留该 interface 的定义名、modport、member
和 top port；内部、非 top ABI 的 interface 对象可在 manual profile 中改写。若同一 interface
类型同时用于内部和顶层，应整体保留其 top ABI 部分。

推荐扩展：

1. 完善 top interface port 的语义引用收集和源范围审计；
2. 对其他与 top 无关的 interface 继续允许加密；
3. 为顶层 interface 设计非 vacuous 的验证方式，再开放其 ABI 重命名。

### 1.2 Aggregate field/parameter 声明位置遮蔽

```systemverilog
module m #(parameter WIDTH=8);
    typedef struct packed {
        logic [WIDTH-1:0] WIDTH;
    } item_t;
endmodule
```

dimension 中的第一个 `WIDTH` 绑定外层 parameter，第二个是新 field。PySlang 11 的
`FieldSymbol` 没有暴露完整 resolved dimension expression，当前 lexical lookup 又无法表达
“field 声明之前”的位置语义。需要位置敏感的 scope lookup 或更严格的 CST/semantic 对应。

参数功能的其余边界也保持 fail-closed：type parameter、package/class/interface/$unit
parameter、parameter array/string/real/struct、`defparam`、复杂 hierarchical reference
和无法证明 owner 的复杂 shadowing 不进入 eligible mapping。

## 2. 尚未实现的语言能力

- type parameter 及 named type override；
- package、class、interface scope parameter/enum/typedef/subroutine；
- `$unit` parameter、parameter array/string/real/struct；
- `defparam` 和层次 parameter 引用；
- extern、DPI import/export、bind、checker、primitive；
- clocking block、virtual interface、modport type selector 引用和 import/export member；
- assignment pattern key、tagged union、constraint 和 assertion 中的全部 field 引用；
- instance array、嵌套/conditional generate 和 generate block 的层次引用；
- 任意深度 lexical shadow 与所有声明位置组合。

## 3. 工程输入与外部 ABI

当前 `inspect-project` 已支持 `project-root + top` 的递归发现、active include/宏依赖、top 闭包、
严格编译和共享 13 类 AST inventory；`encrypt-project` 也支持两入口的 manual profile、mapping
v4、gate audit、metrics 和逐文件 mapping，并由 `decrypt-project` 字节恢复。后续可扩展：

- T033 已完成：冻结 `single_module`/`multi_module` impact、category ownership、共享 registry 和
  machine-readable oracle；
- T034 已完成：统一单文件/filelist 默认 profile；
- T035：两入口 manual multi-module/ABI profile、bounded closure、跨 module parameter、
  module/port/interface 改写和 mapping v4 审计已完成；RISC-V-Vector Formal 不属于其常规验收；
- T036：为三种加密入口增加目标加密率、唯一 effective line 选择、实际率报告和不可达时全候选加密；
- T037：完成 RISC-V-Vector `vector_top` 的 formal-view/formal-align/Yosys 正负例验收，并提供
  根目录 `encrypt.py` 加密/解密演示命令；
- T038（已阻塞，未验收）：修复 RISC-V-Vector parameter/genvar 误分类和 gate 失败，并统一加密率的总行数
  口径；当前仍受六组 occurrences 冻结值偏差和 Formal 验收链路缺失阻塞；
- T039（条件任务）：在 T038 完成后重新评估是否把更多 parameter/shared type 晋级到默认 profile，
  并重新冻结 FIFO/RISC-V-Vector 的数量和 formal oracle；
- library、嵌套 filelist 和更复杂的 include/define 条件组合；
- 未解析 IP/blackbox 的受控模型；
- preserve/allow/deny 规则；
- testbench、SDC、Tcl、波形脚本和软件模型的 mapping 消费工具；
- 对外公开 module、port、parameter、instance path 和协议类型的 ABI 清单。

## 4. 验证工具链

当前 Yosys 适合项目现有可综合子集，但不是完整 SystemVerilog 前端。未来若扩展顶层 interface、
type parameter、package/class 或复杂 assertion，需要先确定能够可靠 elaboration 的 frontend 和
非 vacuous formal 流程。不能仅因为某个 frontend 接受源码，就认为它正确理解了语义。

RISC-V-Vector 当前通过 AST-driven packed-aggregate lowering、concurrent assertion blanking 和
mapping-validated identifier-only alignment 进入 Yosys；这些都是 formal-only 派生物。它们不表示
Yosys 已原生支持相应 SystemVerilog，也不能推广为对任意嵌套 aggregate、外部库或 blackbox 的支持。

建议每项扩展继续保持：

- PySlang gold/gate 无 error；
- 精确 mapping range 和 decrypt 字节恢复；
- Yosys 或替代 formal 的等价正例；
- 人为功能变化的非等价负例；
- 同名、遮蔽和跨文件绑定专项回归。
