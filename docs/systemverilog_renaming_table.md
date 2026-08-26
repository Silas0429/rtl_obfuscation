# SystemVerilog 可加密类型表

当前公共接口只有四个核心组和一个快捷值：`signals`、`ports`、`interface`、`struct`、`all`。
`--category` 必须至少出现一次；旧的细分类和旧别名均报 `CLI_VNEXT_CATEGORY_INVALID`。

| `--category` | 识别对象 | 不建立改名记录的对象 |
| --- | --- | --- |
| `signals` | PySlang module-owned `VariableSymbol/NetSymbol` | module 端口、parameter、interface 成员、struct/union 字段 |
| `ports` | source-backed module `PortSymbol` | selected top 的 ABI 端口按边界保留 |
| `interface` | source-backed interface 类型、标量/数组实例、成员、modport | 匿名 elaboration element、`SystemCallInfo` 等无源码节点 |
| `struct` | 物理 `typedef struct/union` 类型及 `FieldSymbol` 字段 | parameter type、隐式 conversion、canonical aggregate shape |

## 唯一绑定规则

PySlang compile/elaborate 是语义唯一来源。改名记录只来自 source-backed semantic declaration；occurrence
只来自 PySlang 直接 target binding，并且必须有唯一物理 identifier token 和源码字节证据。

- 同一个 interface 的 `ModportPortSymbol` 是已有 interface member 的 semantic alias/occurrence，不是新记录。
- struct member reference 使用 PySlang 直接 `FieldSymbol` target 的 declaration location 绑定；不按名称、文件顺序或 token 顺序选择。
- interface instance array 只为 source-backed array root 建记录，elaborated element 只作 alias，不产生空名称或伪造 range。
- source-less semantic node、隐式 conversion 和 compiler metadata 不产生 edit。
- 不能证明唯一 owner、semantic target 或物理 range 时，相关对象/核心组安全保留并报告位置；绝不猜测。

宏对象本身不加密。宏正文或实参中的 identifier 只有在 PySlang 直接绑定某个选中 RTL symbol 且物理来源
唯一时才作为该 symbol 的 occurrence；多个 symbol 共享同一物理 token 时报告 `macro_origin_conflict` 并保留。

## 结果状态

每个核心组在 mapping 的 `category_outcomes` 中按固定顺序输出 `renamed`、`preserved` 或 `empty`，并给出
candidate、rename、preserve、unsupported 和 issues。记录 action 只有 `rename`、`preserve`、`unsupported`。

- `PASS_FULL`：至少有真实改名，且选中的记录没有保留或不支持对象；
- `PASS_PARTIAL`：gate 严格编译和逐字节恢复通过，但存在明确边界或保留对象；
- `REFUSED_ATOMIC`：绑定、range、编译或恢复校验失败，不发布半成品。

合法的 SystemVerilog 不保证每个 semantic node 都有可编辑的物理 token；稳定性优先于猜测改名。

## 文件后缀

`.sv`、`.v` 使用同一条 PySlang SystemVerilog 语义前端；`.svh`、`.vh` 是 include header；显式 filelist
还可列出只读 `.h` 宏 context header。`.h` 不进入 source unit，也不是宏 rename target。

## 示例

```sh
python rtl_encrypt.py \
  --filelist design.f \
  --top <可选顶层> \
  --category signals \
  --category interface \
  --output-dir <尚不存在的目录>
```

选择四组：

```sh
--category all
```
