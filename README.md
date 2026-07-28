# RTL Obfuscation

本项目用于加密 SystemVerilog 源码中的标识符，并生成可用于恢复原始源码的映射报告。加密只
改变名称，不改变 RTL 的预期功能。

请从仓库根目录运行，使用 Python 3.10 或更高版本，并确保当前 Python 环境已经提供
PySlang 11.x。无需安装本项目；可先查看两个脚本的帮助：

```sh
python rtl_encrypt.py --help
python rtl_decrypt.py --help
```

## 先选择输入模式

| 模式 | 输入范围 | `--top` | 普通名称范围 | ABI 范围 |
| --- | --- | --- | --- | --- |
| 单文件 | 一个 `.sv` 及其 include | 可选 | 该输入文件 | 只有提供 top 且显式授权时 |
| filelist | `.f` 中全部 `.sv/.svh` | 可选 | 全部清单文件 | 仅 top 闭包内显式授权对象 |
| project-root | 自动发现的 top 闭包 | 必填 | 自动发现闭包 | 仅闭包内显式授权对象 |

`--filelist` 支持可选 `--top`。filelist 中的所有 physical files 都进入普通名称加密范围；
`--top` 只确定 ABI 分析边界，不会把普通名称加密缩小到 top closure。selected top 的名称和
外部端口边界始终保持不变。

不提供 `--category` 时，默认加密 13 类常用内部名称。一旦手动提供 `--category`，默认集合
不会自动追加；快捷值 `all` 也只代表默认 13 类，不包含额外 ABI 类。module、port 和
interface 等额外类型必须用 `--category` 显式选择；跨模块 ABI 名称还必须逐类使用
`--abi-category` 授权，只选择 category 不代表对应 ABI 名称会被替换。

所有可选名称及 ABI 授权方式见
[SystemVerilog 可加密类型表](docs/systemverilog_renaming_table.md)。

## 单文件加密

### 基础命令格式

```sh
python rtl_encrypt.py \
  --input <输入文件> \
  --source-root <源码根目录> \
  --output-dir <加密源码目录> \
  --map <映射报告.json> \
  --metrics <覆盖率报告.json>
```

### 必填参数

- `--input`：要加密的一个 `.sv` 文件，通常写相对于 `--source-root` 的路径。
- `--source-root`：输入文件及其相对 include 的根目录。
- `--output-dir`：加密后源码的输出目录。
- `--map`：加密映射与执行报告。
- `--metrics`：加密覆盖率报告。

### 项目示例

示例使用 `rtl_samples/11_supported_obfuscation.sv`。

### 示例架构

这一个 physical file 同时包含两个模块：

| 模块 | 关系 |
| --- | --- |
| `sample11_supported_obfuscation` | 示例顶层，包含参数、信号、类型、function、task 和 generate |
| `sample11_helper` | 被示例顶层实例化的 helper |

不提供 `--category`，因此使用默认 13 类。

### 运行示例

从仓库根目录执行：

```sh
single_work="$(mktemp -d /tmp/rtl-obfuscation-single.XXXXXX)"

python rtl_encrypt.py \
  --input 11_supported_obfuscation.sv \
  --source-root rtl_samples \
  --output-dir "$single_work/gate" \
  --map "$single_work/mapping.json" \
  --metrics "$single_work/metrics.json"
```

## Filelist 多文件加密

### 基础命令格式

```sh
python rtl_encrypt.py \
  --filelist <文件清单.f> \
  --source-root <源码根目录> \
  --output-dir <加密源码目录> \
  --map <映射报告.json> \
  --metrics <覆盖率报告.json>
```

### 必填参数

- `--filelist`：列出所有输入 `.sv/.svh` 的 `.f` 文件，通常写相对于
  `--source-root` 的路径。
- `--source-root`：filelist、清单文件和相对 include 的根目录。
- `--output-dir`、`--map`、`--metrics`：三个必须且不能预先存在的输出。

`--top` 在 filelist 模式中是可选参数。提供它不会缩小普通名称的输入范围：清单中的全部文件
仍会处理；它只用于确定闭包内哪些 ABI 名称可以在显式授权后加密。

### 项目示例

示例使用 `rtl_samples/example_fifo/design.f`。

### 示例架构

清单按编译顺序显式列出四个文件：

| 文件 | 架构角色 |
| --- | --- |
| `fifo_if.sv` | 定义 FIFO 的 interface 与 modport |
| `fifo_storage.sv` | 实现数据存储 |
| `fifo_ctrl.sv` | 连接 interface 与存储模块 |
| `fifo_top.sv` | `fifo_top` 顶层适配器 |

### 运行示例

这个例子增加可选的 `--top fifo_top`，但仍使用默认 13 类：

```sh
filelist_work="$(mktemp -d /tmp/rtl-obfuscation-filelist.XXXXXX)"

python rtl_encrypt.py \
  --filelist design.f \
  --source-root rtl_samples/example_fifo \
  --top fifo_top \
  --output-dir "$filelist_work/gate" \
  --map "$filelist_work/mapping.json" \
  --metrics "$filelist_work/metrics.json"
```

## Project-root 项目加密

### 基础命令格式

```sh
python rtl_encrypt.py \
  --project-root <项目根目录> \
  --top <顶层模块名> \
  --output-dir <加密源码目录> \
  --map <映射报告.json> \
  --metrics <覆盖率报告.json>
```

### 必填参数

- `--project-root`：需要自动发现源码的项目目录。
- `--top`：发现依赖闭包所用的顶层模块名。
- `--output-dir`、`--map`、`--metrics`：三个必须且不能预先存在的输出。

project-root 模式不接受 `--source-root`，也不读取用户提供的 filelist。

### 项目示例

示例仍使用 `rtl_samples/example_fifo`。

### 示例架构

工具从 `fifo_top` 开始解析模块与 interface 依赖，自动发现与上一个示例相同的四文件闭包及
编译顺序：

```text
fifo_top
├── fifo_if
└── fifo_ctrl
    ├── fifo_if
    └── fifo_storage
```

### 运行示例

这个示例展示当前支持范围的完整选择：`all` 选择默认 13 类，另外三个 category 补入默认
集合之外的 module、port 和四种 interface 类型；随后用 `--abi-category` 逐类授权闭包内
允许变化的跨模块名称。selected top 的名称和外部端口仍会保留。

```sh
project_work="$(mktemp -d /tmp/rtl-obfuscation-project.XXXXXX)"

python rtl_encrypt.py \
  --project-root rtl_samples/example_fifo \
  --top fifo_top \
  --output-dir "$project_work/gate" \
  --map "$project_work/mapping.json" \
  --metrics "$project_work/metrics.json" \
  --category all --category modules --category ports --category interface \
  --abi-category parameters --abi-category typedefs \
  --abi-category struct_types --abi-category struct_fields --abi-category union_fields \
  --abi-category modules --abi-category ports \
  --abi-category interfaces --abi-category interface_instances \
  --abi-category interface_ports --abi-category modports
```

这里的 `fifo_bus` 属于 `interface_instances`，但当前实现把 selected top 内声明的这个实例标为
`selected_top_boundary`，因此即使同时选择 category 和 ABI category 也仍会保留。这是当前
边界；“完整选择”不表示所有词法标识符都会被替换。

## 解密

### 基础命令格式

```sh
python rtl_decrypt.py \
  --map <加密映射报告.json> \
  --gate-dir <加密源码目录> \
  --source-root <原始源码根目录> \
  --output-dir <恢复源码目录> \
  --report <恢复报告.json>
```

五个参数都必须提供：

- `--map`：加密时生成的映射报告。
- `--gate-dir`：加密时生成的源码目录。
- `--source-root`：原始源码根目录，用于完整性校验。
- `--output-dir`：恢复后的源码目录。
- `--report`：恢复过程报告。

在上面的 project-root 示例之后，可在同一个 shell 中继续执行：

```sh
python rtl_decrypt.py \
  --map "$project_work/mapping.json" \
  --gate-dir "$project_work/gate" \
  --source-root rtl_samples/example_fifo \
  --output-dir "$project_work/restored" \
  --report "$project_work/restore.json"
```

恢复成功时，所有 physical files 都与原始输入逐字节一致。

## `rtl_encrypt.py` 完整选项

| 选项 | 是否必需 | 用法 |
| --- | --- | --- |
| `--input PATH` | 三选一 | 单文件模式；路径相对于 `--source-root`，也可使用绝对路径。 |
| `--filelist PATH` | 三选一 | filelist 模式；路径相对于 `--source-root`，也可使用绝对路径。 |
| `--project-root PATH` | 三选一 | project-root 模式；必须同时提供 `--top`，且不能提供 `--source-root`。 |
| `--source-root PATH` | single/filelist 必需 | 单文件或 filelist 的源码根目录。 |
| `--top NAME` | project-root 必需，其他模式可选 | 顶层模块名；在 filelist 模式中不缩小普通名称的输入范围，只限定 ABI 闭包。 |
| `--include-dir PATH` | 可选，可重复 | 添加 include 目录；相对路径以源码根目录为基准。 |
| `--define NAME[=VALUE]` | 可选，可重复 | 添加预处理宏，例如 `--define SYNTHESIS`。 |
| `--category NAME` | 可选，可重复 | 选择加密类型；不提供时使用默认 13 类。 |
| `--abi-category NAME` | 可选，可重复 | 明确允许对应的跨模块名称；需要 `--top`，且该类型也必须由 `--category` 选择。 |
| `--encryption-rate RATE` | 可选 | 加密比例，必须大于 `0` 且不大于 `1`。 |
| `--name-length N` | 可选 | 新名称长度，最小为 `4`，默认值为 `20`。 |
| `--output-dir PATH` | 必需 | 加密源码目录；目标不能已存在，父目录必须存在。 |
| `--map PATH` | 必需 | 映射报告；目标不能已存在，父目录必须存在。 |
| `--metrics PATH` | 必需 | 覆盖率报告；目标不能已存在，父目录必须存在。 |

开发和维护信息见[项目结构](docs/project_structure.md)。
