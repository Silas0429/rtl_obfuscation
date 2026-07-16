# 未来扩展与已知问题

本文件只记录当前交付范围之外的事项。已经实现的功能和使用方法见根目录
[`README.md`](../README.md)，不要在本文件复制使用说明。

## 1. 优先解决的问题

### 1.1 顶层 interface port ABI

当前不能可靠处理：

```systemverilog
module top(bus_if.slave bus);
    assign observed = bus.data;
endmodule
```

保留 top port 名 `bus` 并不足够；`bus_if`、`slave` 和 `data` 都属于顶层 ABI。现有实现尚未
形成这四类对象的保护闭包，modport 引用和顶层 interface member access 也没有完整收集。
此外，当前 Icarus/Yosys 对该语法的前端支持不足，Yosys 可能把 `bus.data` 当作隐式信号，
导致 formal 证明失去意义。

当前规避方式：保留该 interface 的定义名、modport、member 和 top port，不启用
`interfaces`、`interface_ports`、`modports`。若同一 interface 类型同时用于内部和顶层，
应整体保留。

推荐扩展：

1. 从 top 的 `InterfacePortSymbol` 计算 interface definition、modport 和 member ABI 闭包；
2. 默认冻结闭包并在 mapping/metrics 中报告 preserved 原因；
3. 对其他与 top 无关的 interface 继续允许加密；
4. 为顶层 interface 设计非 vacuous 的验证方式，再开放其 ABI 重命名。

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

## 2. 尚未实现的语言能力

- type parameter 及 named type override；
- package、class、interface scope parameter/enum/typedef/subroutine；
- `defparam` 和层次 parameter 引用；
- extern、DPI import/export、bind、checker、primitive；
- clocking block、virtual interface、modport type selector 引用和 import/export member；
- assignment pattern key、tagged union、constraint 和 assertion 中的全部 field 引用；
- instance array、嵌套/conditional generate 和 generate block 的层次引用；
- 任意深度 lexical shadow 与所有声明位置组合。

## 3. 工程输入与外部 ABI

当前 filelist 只接受显式 `.sv` 相对路径。后续可扩展：

- `project-root + top` 的递归发现、依赖闭包和工程级加密已经形成分阶段实施方案，见
  [`project_root_top_roadmap.md`](project_root_top_roadmap.md)；该文档描述计划，不代表当前
  已交付能力；
- include directory、define、library 和嵌套 filelist；
- 未解析 IP/blackbox 的受控模型；
- preserve/allow/deny 规则；
- testbench、SDC、Tcl、波形脚本和软件模型的 mapping 消费工具；
- 对外公开 module、port、parameter、instance path 和协议类型的 ABI 清单。

## 4. 验证工具链

当前 Yosys 适合项目现有可综合子集，但不是完整 SystemVerilog 前端。未来若扩展顶层 interface、
type parameter、package/class 或复杂 assertion，需要先确定能够可靠 elaboration 的 frontend 和
非 vacuous formal 流程。不能仅因为某个 frontend 接受源码，就认为它正确理解了语义。

建议每项扩展继续保持：

- PySlang gold/gate 无 error；
- 精确 mapping range 和 decrypt 字节恢复；
- Yosys 或替代 formal 的等价正例；
- 人为功能变化的非等价负例；
- 同名、遮蔽和跨文件绑定专项回归。
