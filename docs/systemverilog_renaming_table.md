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

## 死源码引用保留

未被 elaborate 的源码区域里的 identifier 不产生任何语义引用节点，PySlang 也不为此报任何诊断。
两种形态属于死源码：只在未选中 generate 分支里被实例化、因而没有任何语义 body 的设计单元；
以及已 elaborate 单元内 `isUninstantiated` 的 generate 分支。

一个符号的旧名只要在死源码里被写出，就报告 `unelaborated_reference` 并保留该条记录：
那些 token 物理存在而语义不可见，只改声明会把旧名留在 gate 里变成隐式 net。死源码里拼写相同的
token 也可能属于另一个同名符号，所以这条规则是保守保留，不做名字猜测式改写。保留逐条生效，
同组内其他已证明的记录仍然改名。

## 逐符号名字完整性

改名的前置条件是一条与形状无关的判据：对旧名为 `n` 的符号，令 T 为源码集合中所有拼写 `n` 的
物理 identifier token；只有当 T 中不存在**未归属** token 时才改名。未归属即既没有归属给任何
语义引用，也没有归属给任何声明。只要存在一个未归属的同名 token，所有拼写 `n` 的记录都报告
`incomplete_name_coverage` 并保留。

归属证据有三类，缺一不可：本次运行自身记录的声明与 occurrence 物理 range；设计中每一个具名
symbol 的声明 token（含 parameter、genvar、module、subroutine 等四组之外的名字，以及嵌套聚合
的成员）；以及"最小包含且目标同名的引用"这条通用规则。

分母是 CST 里全部 `Identifier` token，逐字节校验，宏位置先经 `SourceManager` 还原。唯一被排除的
是 `SystemIdentifier`（`$clog2` 一类语言内建，永远不可能是改名目标）。**不得**因为"暂时没有绑定
规则"而把某类 token 排除在分母之外——那正是本判据要抓的 token。无法定位或校验失败的 token 同样
按未归属处理。

该判据与形状无关，因此一次性覆盖已知与未知的 fail-open，代价是覆盖率下降；这是"改得少但可证明
正确"对"编译过但功能错"的取舍。`unelaborated_reference` 更具体，诊断价值更高，因此优先级在前，
已被它保留的记录不再改报本原因。保留逐条生效，不升级为整组。

## 结果状态

每个核心组在 mapping 的 `category_outcomes` 中按固定顺序输出 `renamed`、`preserved` 或 `empty`，并给出
candidate、rename、preserve、unsupported 和 issues。记录 action 只有 `rename`、`preserve`、`unsupported`。

- `PASS_FULL`：至少有真实改名，且选中的记录没有保留或不支持对象；
- `PASS_PARTIAL`：gate 严格编译和逐字节恢复通过，但存在明确边界或保留对象；
- `REFUSED_ATOMIC`：绑定、range、编译或恢复校验失败，不发布半成品。

合法的 SystemVerilog 不保证每个 semantic node 都有可编辑的物理 token；稳定性优先于猜测改名。

## 文件后缀

`.sv`、`.v` 使用同一条 PySlang SystemVerilog 语义前端；`.svh`、`.vh` 是 include header；显式 filelist
还可列出只读 `.h` 宏 context header，以及用裸路径列出的 `.vic` compilation-unit 参数 context。
`.h/.vic` 不进入 source unit，也不是 rename target；已显式列出的同一规范化 `.vic` 路径可被
source/header include，但 include-only `.vic` 不支持。`.vic` 也不支持 `-v`、single-file 或
project-root 自动发现。

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
