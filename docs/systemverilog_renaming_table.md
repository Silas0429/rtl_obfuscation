# SystemVerilog 可加密类型表

`python rtl_encrypt.py` 使用 `--category` 选择要加密的名称类型。单文件和不带 `--top`
的 filelist 默认选择前 13 类；带 `--top` 的 filelist，以及只提供
`--source-root + --top` 的项目加密，默认选择全部 19 类。

| `--category` 值 | 加密内容 | 默认 13 类 | 未提供 `--top` | filelist/项目加密提供 `--top` |
| --- | --- | --- | --- | --- |
| `signals` | module 内的变量和连线 | 是 | 加密 module 内部名称 | 加密 module 内部名称 |
| `parameters` | parameter、localparam 和 generate 参数 | 是 | 加密只在 module 内部使用的参数 | 跨 module 使用的参数及引用会一致改名 |
| `enum_values` | 枚举值；仅在原始词法 token 与语义 ranges 完整一致时加密，覆盖不完整的单条枚举值保留 | 是 | 加密 | 加密 |
| `genvars` | generate-for 使用的 genvar | 是 | 加密 | 加密 |
| `functions` | function 名称 | 是 | 普通物理 function 的 declaration、return-name references、calls 与直接 closing label `endfunction : name` 使用同一名称；无 closing label 时不新增引用，宏生成 label 不支持 | 普通物理 function 的 declaration、return-name references、calls 与直接 closing label `endfunction : name` 使用同一名称；无 closing label 时不新增引用，宏生成 label 不支持 |
| `tasks` | task 名称 | 是 | 加密 | 加密 |
| `arguments` | function 和 task 的参数 | 是 | 普通物理 function 参数的 declaration、body references 与 named-call label 使用同一名称；task/method/macro named label 不支持 | 普通物理 function 参数的 declaration、body references 与 named-call label 使用同一名称；task/method/macro named label 不支持 |
| `instances` | module 实例名称 | 是 | 加密 | 加密 |
| `generate_blocks` | 命名 generate block | 是 | 加密 | 加密 |
| `typedefs` | 普通 typedef 类型名称 | 是 | 加密只在 module 内部使用的类型 | 跨 module 使用的类型及引用会一致改名 |
| `struct_types` | struct 和 union 类型名称 | 是 | 加密只在 module 内部使用的类型 | 跨 module 使用的类型及引用会一致改名 |
| `struct_fields` | struct 成员名称 | 是 | 加密只在 module 内部使用的成员 | 跨 module 使用的成员及引用会一致改名 |
| `union_fields` | union 成员名称 | 是 | 加密只在 module 内部使用的成员 | 跨 module 使用的成员及引用会一致改名 |
| `modules` | module 名称 | 否 | 保留 | 一致加密子 module 声明、实例化引用和直接 closing label `endmodule : name`；top module 名称及 closing label 保留 |
| `ports` | module 端口名称 | 否 | 保留 | 加密子 module 端口和连接引用；top module 对外端口保留 |
| `interfaces` | interface 类型名称 | 否 | 保留 | interface 类型及引用会一致改名 |
| `interface_instances` | interface 实例名称 | 否 | 保留 | 加密符合条件的 interface 实例；top module 内直接声明的实例名当前保留 |
| `interface_ports` | interface 端口和成员名称 | 否 | 保留 | interface 端口、成员及引用会一致改名 |
| `modports` | modport 名称 | 否 | 保留 | modport 名称及引用会一致改名 |

## 默认选择与快捷值

- 不提供 `--category` 时，单文件和不带 `--top` 的 filelist 加密表中的默认 13 类。
- 不提供 `--category` 时，带 `--top` 的 filelist 和项目加密会处理全部 19 类。
- 一旦手动使用 `--category`，工具只处理用户选择的类型，不再追加默认类型。
- 快捷值 `all`（`--category all`）：选择全部 19 类。
- 快捷值 `struct`（`--category struct`）：等同于
  `--category struct_types --category struct_fields`。
- 快捷值 `interface`（`--category interface`）：等同于
  `--category interfaces --category interface_instances --category interface_ports --category modports`。

filelist 提供 `--top`，或者只提供 `--source-root + --top` 进行项目加密后，工具会自动
保证所选类型在子 module 定义和调用位置使用同一个新名称。top module 名称和对外端口
始终保留。

当前版本会保留 top module 内部直接声明的 interface 实例名；interface 类型和成员仍会
加密。

## 常用示例

只加密信号和 module 实例：

```sh
--category signals --category instances
```

只加密 struct/union 类型和 struct 成员：

```sh
--category struct --category union_fields
```

在带 `--top` 的 filelist 或项目加密中，只加密子 module 名称、端口和 interface：

```sh
--category modules --category ports --category interface
```

选择当前支持的全部类型：

```sh
--category all
```
