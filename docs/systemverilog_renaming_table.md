# SystemVerilog 可加密类型表

`python rtl_encrypt.py` 使用 `--category` 选择要加密的名称类型。单文件和不带 `--top`
的 filelist 默认选择前 13 类；带 `--top` 的 filelist，以及只提供
`--source-root + --top` 的项目加密，默认选择全部 19 类。

宏永远不是 rename target：宏定义名、形式参数、调用名、实参 spelling、宏正文和展开 token
不进入 mapping 或 edit。宏展开位置落入普通物理 module 时，只保护该 owner 及必要的精确绑定
target；无宏 sibling 仍可改名。非 module 宏不单独阻断无关 signals，但宏生成 module definition
或无法安全隔离的真实改写对象继续 fail-closed。

filelist 中列出但当前 PySlang 编译配置未使用到的普通 module 不参与改名：不会建立改名记录或源码编辑，
但仍原样保留在 gate、manifest 和 restore 中。其他能唯一对应到源码范围的 module 按下表处理；若一个
module 无法唯一对应到源码范围，工具会停止并报告错误。

默认选择只表示工具会检查这些类型，不表示任意工程中的每种写法都能改名。真实工程建议从少量
`--category` 开始；结果中的 `rename` 是实际改名，`preserve` 和 `unsupported` 是为避免错误而
保留的对象。`rename=0` 不能视为该类型已经完整支持。

每次运行还会给出明确结果：`PASS_FULL` 表示所选 graph 有实际改名且没有 `preserve/unsupported`；
`PASS_PARTIAL` 表示 gate/恢复通过但存在保留、不支持或零改名；`REFUSED_ATOMIC` 表示无法证明安全性，
不发布半成品输出。只有 `PASS_FULL` 才表示当前输入闭包内的所选类别完成了完整改名。

文件后缀不是新的加密类别：`.sv`、`.v` source unit 以及被 include 的 `.svh`、`.vh` 共用同一条
PySlang SystemVerilog 语义流水线；显式 filelist 还可提供只读 `.h` 宏 context header。`.h` 不进入
compile order、不产生宏 rename，也不被 single-file 或 project-root 自动扫描。工具不承诺 strict
legacy-Verilog 方言，也不接受大写后缀或把 header 当作独立 source unit。

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
| `typedefs` | 普通 typedef 类型名称；只有原始词法 token ranges 与 declaration 加已有语义 references ranges 精确相等时才允许改名，覆盖不完整的单条 typedef 保留 | 是 | 加密只在 module 内部使用且覆盖完整的类型 | 跨 module 使用且覆盖完整的类型及引用会一致改名；证据不足时整条 typedef 不产生 edit |
| `struct_types` | struct 和 union 类型名称 | 是 | 加密只在 module 内部使用的类型 | 跨 module 使用的类型及引用会一致改名 |
| `struct_fields` | struct 成员名称 | 是 | 加密只在 module 内部使用的成员；普通物理 struct alias 的 direct named assignment-pattern key 会按 exact alias owner 与字段名一致改写 | 跨 module 使用的成员及引用会一致改名；union/array/default/type/literal/宏或 anonymous pattern key 不在此闭包内 |
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
