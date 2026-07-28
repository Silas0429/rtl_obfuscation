# SystemVerilog 可加密类型表

在 `python rtl_encrypt.py` 命令中使用一个或多个 `--category` 选择要加密的名称类型。

| 选项值 | 加密对象 | 默认选择 | 跨模块名称要求 |
| --- | --- | --- | --- |
| `signals` | 模块内的变量和连线 | 是 | 不适用 |
| `parameters` | parameter、localparam 和 generate 迭代参数 | 是 | 跨模块参数需要 `--top`，并同时使用 `--category parameters --abi-category parameters` |
| `enum_values` | 枚举值 | 是 | 不适用 |
| `genvars` | generate-for 的 genvar | 是 | 不适用 |
| `functions` | function 名称 | 是 | 不适用 |
| `tasks` | task 名称 | 是 | 不适用 |
| `arguments` | function 和 task 的参数 | 是 | 不适用 |
| `instances` | 模块实例名称 | 是 | 不适用 |
| `generate_blocks` | 命名 generate block | 是 | 不适用 |
| `typedefs` | 非 struct/union 的 typedef 名称 | 是 | 跨模块使用的类型需要 `--top`，并同时使用 `--category typedefs --abi-category typedefs` |
| `struct_types` | struct/union 类型名称 | 是 | 跨模块使用的类型需要 `--top`，并同时使用 `--category struct_types --abi-category struct_types` |
| `struct_fields` | struct 成员名称 | 是 | 跨模块使用的成员需要 `--top`，并同时使用 `--category struct_fields --abi-category struct_fields` |
| `union_fields` | union 成员名称 | 是 | 跨模块使用的成员需要 `--top`，并同时使用 `--category union_fields --abi-category union_fields` |
| `modules` | 模块名称 | 否 | 需要 `--top`，并同时使用 `--category modules --abi-category modules` |
| `ports` | 普通模块端口名称 | 否 | 需要 `--top`，并同时使用 `--category ports --abi-category ports` |
| `interfaces` | interface 名称 | 否 | 需要 `--top`，并同时使用 `--category interfaces --abi-category interfaces` |
| `interface_instances` | interface 实例名称 | 否 | 闭包内符合条件的对象需要 `--top`，并同时使用 `--category interface_instances --abi-category interface_instances`；但 selected top 内声明的实例当前按 `selected_top_boundary` 保留 |
| `interface_ports` | interface 端口或成员名称 | 否 | 需要 `--top`，并同时使用 `--category interface_ports --abi-category interface_ports` |
| `modports` | modport 名称 | 否 | 需要 `--top`，并同时使用 `--category modports --abi-category modports` |

## 默认选择和快捷值

不提供 `--category` 时，默认选择表中的前 13 类。快捷值 `all` 也只展开这 13 类，不包含
`modules`、`ports` 或 interface 相关类型。

- `--category struct` 等同于
  `--category struct_types --category struct_fields`。
- `--category interface` 等同于
  `--category interfaces --category interface_instances --category interface_ports --category modports`。

一旦显式提供任意 `--category`，默认类型不会自动追加。例如，同时选择默认 13 类、模块名和端口名：

```sh
--top top_module \
--category all --category modules --category ports \
--abi-category modules --abi-category ports
```

跨模块名称必须满足三项要求：

1. 提供 `--top`；
2. 用 `--category` 选择该类型；
3. 用 `--abi-category` 再次明确允许该类型。

`interface_instances` 还有一个当前边界：双重授权只允许处理 top closure 内其他符合条件的
interface instance。selected top 内声明的实例仍按 `selected_top_boundary` 保留；例如 FIFO
示例中的 `fifo_bus`，即使同时选择 category 和 ABI category 也仍会保留。
