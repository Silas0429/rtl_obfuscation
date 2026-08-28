# RTL Obfuscation

本项目使用 PySlang 的编译与 elaboration 结果识别 RTL 名称，并对有完整物理绑定证据的对象进行改名。
实际工程请优先使用显式 filelist；工具不修改宏对象，也不会猜测 owner、scope 或源码 token。

## 3 分钟快速开始

```sh
quick_work="$(mktemp -d /tmp/rtl-obfuscation-quick.XXXXXX)"
python rtl_encrypt.py \
  --filelist rtl_samples/example_fifo/design.f \
  --top fifo_top \
  --category signals \
  --output-dir "$quick_work/gate"
cat "$quick_work/gate/encryption_summary.txt"
python rtl_decrypt.py \
  --map "$quick_work/gate/mapping.json" \
  --gate-dir "$quick_work/gate" \
  --output-dir "$quick_work/restored"
```

成功条件：命令退出码为 `0`，`summary.strict_compile_passed` 和
`summary.restored_byte_identical` 均为 `true`。结果中的 `rename`、`preserve`、`unsupported`
分别表示实际改名、按边界保留、因证据不足保留。

## Filelist 模式（真实工程首选）

```sh
python rtl_encrypt.py \
  --filelist design.f \
  --top <可选的顶层模块名> \
  --category signals \
  --output-dir <尚不存在的输出目录>
```

`--category` 必须显式提供，可重复使用，允许值只有：
`signals`、`ports`、`interface`、`struct`、`all`。`all` 按固定顺序展开为四个核心组。

filelist 中的 `.sv/.v` 是 source unit；被 include 的 `.svh/.vh` 和显式列出的 `.h` 是只读上下文，
不会成为宏 rename target。`-f` 嵌套 filelist、`+incdir+`、`+define+`、`$NAME` 和 `${NAME}`
按出现顺序处理。filelist 模式禁止同时提供 `--source-root`；源码根目录由 filelist 和 include
路径自动推导。

宏定义名、形式参数名、调用名和预处理结构不进入 mapping。宏正文或实参中的 token 只有在 PySlang
直接绑定到某个选中 RTL symbol 且能唯一对应物理 token 时，才作为该 symbol 的 occurrence；冲突时
保留对应对象，不发布不确定的 gate。

## 四个核心加密组

| 类别 | 内容 |
| --- | --- |
| `signals` | module 内部的 Variable/Net，不包含端口、parameter、interface 成员和 struct 字段 |
| `ports` | module 的 source-backed 端口；selected top 的对外 ABI 保留 |
| `interface` | interface 类型、source-backed 标量/数组实例、成员和 modport；数组 element 只是语义 alias |
| `struct` | 物理 `typedef struct/union` 类型及其字段；隐式 conversion 不伪造 occurrence |

无法从 PySlang semantic target 证明唯一物理 declaration/occurrence 时安全保留对应对象或核心组。
合法的 PySlang 编译不等于每个 semantic node 都有可改写的物理 token。

## 三种输入模式

| 模式 | 参数 |
| --- | --- |
| 单文件 | 仅 `--input FILE` |
| filelist | `--filelist FILE`，`--top` 可选 |
| project-root | `--source-root DIR --top TOP` |

三种模式严格互斥：单文件不能附带 `--source-root` 或 `--top`；filelist 不能附带
`--source-root`；project-root 不能附带 `--input` 或 `--filelist`。输入模式错误会在输出创建前报告
稳定错误码和具体 detail/message。

project-root 是辅助入口，会从源码根目录发现依赖；单文件用于快速试用。两者不改变四组识别规则。

## 输出、恢复和 schema

输出目录包含加密 RTL、canonical `design.f`、`mapping.json`、`metrics.json`、
`mapping_table.csv` 和 `encryption_summary.txt`。mapping 使用
`format=rtl-obfuscation.mapping`、`schema_version=2`；每条记录包含 category、kind、
semantic kind、物理 declaration/occurrences、action 和 reason。

```sh
python rtl_decrypt.py \
  --map <gate>/mapping.json \
  --gate-dir <gate> \
  --output-dir <尚不存在的恢复目录>
```

恢复只依赖本次 gate 的 mapping 和物理文件。schema 1 不兼容读取，错误码为
`RESTORE_MAPPING_VERSION_UNSUPPORTED`。

`PASS_FULL` 表示本次选中对象全部改名；存在明确边界或安全保留时为 `PASS_PARTIAL`；验证或绑定失败为
`REFUSED_ATOMIC`，不会发布半成品。

保留记录的 `reason` 说明为什么该对象没有改名。常见值：

| `reason` | 含义 |
| --- | --- |
| `selected_top_boundary` | selected top 的 ABI 对象按边界保留 |
| `outside_top_closure` | 对象不在 selected top 的层次闭包内 |
| `macro_origin_conflict` | 一个物理 token 被多个符号共享，来源无法唯一确定 |
| `hierarchical_prefix_unsupported` | 该对象需要层次引用前缀改写，当前不支持 |
| `source_binding_incomplete` | 该记录缺少完整的声明与引用绑定证据 |
| `unelaborated_reference` | 旧名还写在未被 elaborate 的源码里，那里的引用语义不可见 |

`unelaborated_reference` 覆盖只在未选中 generate 分支或从未 elaborate 的设计单元里出现的引用。
那些 token 物理存在但不产生任何语义引用，严格编译也不报错，所以只改声明会把旧名留在加密结果里
变成隐式 net。工具选择保留该符号：宁可少改，不可改错。

## 常用参数

| 选项 | 说明 |
| --- | --- |
| `--include-dir PATH` | include 目录，可重复 |
| `--define NAME[=VALUE]` | 预处理宏，可重复 |
| `--category NAME` | 四组之一或 `all`，可重复且必填 |
| `--name-length N` | 新名称长度，最小 4，默认 20 |
| `--encryption-rate RATE` | 目标行加密率，`0 < RATE <= 1` |
| `--map PATH` | 自定义 mapping 路径 |
| `--metrics PATH` | 自定义 metrics 路径 |

## 安装

准备 Python 3.10+ 和 PySlang 11.x 后，在仓库根目录运行：

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install --no-index --no-deps \
  wheel/pyslang-11.0.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
```

更多开发者说明见 [SystemVerilog 可加密类型表](docs/systemverilog_renaming_table.md)、
[Formal 流程](docs/formal_verification.md) 和 [开发文档索引](docs/development/README.md)。
