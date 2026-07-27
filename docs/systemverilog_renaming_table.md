# SystemVerilog 重命名表

本表描述当前 vNext 产品支持的 canonical category。所有 entry 必须来自 PySlang semantic
object，并通过唯一 SourceCatalog owner registry、source-byte range audit 和 actual gate 验证。

## Canonical registry

固定顺序为：

```text
signals parameters enum_values genvars functions tasks arguments instances
generate_blocks typedefs struct_types struct_fields union_fields modules ports
interfaces interface_instances interface_ports modports
```

默认选择和 `all` 展开前 13 类：`signals`、`parameters`、`enum_values`、`genvars`、
`functions`、`tasks`、`arguments`、`instances`、`generate_blocks`、`typedefs`、
`struct_types`、`struct_fields`、`union_fields`。alias `struct` 展开为
`struct_types + struct_fields`，alias `interface` 展开为
`interfaces + interface_instances + interface_ports + modports`。

## Category 语义

| Category | semantic object | 必须同步修改 |
| --- | --- | --- |
| `signals` | module variable/net | declaration、semantic expression、select 和 member base |
| `parameters` | value parameter、localparam、generate iteration parameter | declaration、dimension、expression、generate 和 named override |
| `enum_values` | semantic enum value | declaration 和 bound expression |
| `genvars` | generate-for genvar | declaration、condition、iteration 和 body |
| `functions` | subroutine/function | declaration、bound return variable 和 call/reference |
| `tasks` | task subroutine | declaration 和 bound reference |
| `arguments` | function/task formal argument | declaration 和 subroutine body |
| `instances` | named module instance | instance declaration |
| `generate_blocks` | named generate block | semantic generate declaration |
| `typedefs` | non-aggregate type alias | declaration 和 semantic type use |
| `struct_types` | struct/union aggregate type alias | declaration 和 semantic type use |
| `struct_fields` | struct field | declaration 和 semantic member access |
| `union_fields` | union field | declaration 和 semantic member access |
| `modules` | module definition | declaration 和 semantic hierarchy type |
| `ports` | ordinary module port | declaration、semantic body use 和 named connection |
| `interfaces` | interface definition | declaration、instance type 和 interface-port type |
| `interface_instances` | named interface instance | instance declaration |
| `interface_ports` | interface port/member | declaration、member use、connection 和 modport member |
| `modports` | modport declaration | declaration and bound interface use |

`module`、`interface`、type、subroutine、generate 和 `$unit` owners 都必须在同一个 semantic
owner registry 中实际存在。一个 physical range 只能归属一个 symbol；精确重复、部分重叠、
multiple owner 或缺少 source-byte evidence 必须 fail-closed。

## ABI 与 top boundary

可成为 `module_abi` 的类别固定为：

```text
parameters typedefs struct_types struct_fields union_fields modules ports
interfaces interface_instances interface_ports modports
```

有 top 时，只有显式 ABI opt-in、位于 top closure 且 declaration/reference 完整绑定的对象可
改写；selected top ABI 保持 preserved，closure 外对象保持 preserved。无 top 时 ABI 对象不进入
rename。`all` 不隐式启用 ABI category。

同名文本不等于同一语义对象。不同 module/type/subroutine owner、aggregate field、named
connection、generate/genvar 和 iteration parameter 必须保持独立 identity；无法证明时不得用
全文件拼写搜索补齐 mapping。

## 输入与外部边界

三种输入入口共享同一 vNext semantic path。testbench、SDC、Tcl、软件模型、外部层次路径、
package/class/DPI/bind/clocking/virtual-interface 语义不会被隐式改写；超出 semantic coverage
的输入应以稳定错误 fail-closed。
