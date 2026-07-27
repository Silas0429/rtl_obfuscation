# RTL Obfuscation

在仓库根目录使用已安装 `pyslang` 的 Python 运行以下命令。

`encrypt-vnext` 是当前唯一的加密子命令。`vNext` 只是这套统一实现沿用的内部名称，不是
另一种加密算法，也不是需要用户选择的运行模式。

## 单文件加密

`--input` 使用相对于 `--source-root` 的路径：

```sh
mkdir -p /tmp/rtl-obfuscation-single
python -m rtl_obfuscator.rewrite encrypt-vnext \
  --input 11_supported_obfuscation.sv \
  --source-root rtl_samples \
  --output-dir /tmp/rtl-obfuscation-single/gate \
  --map /tmp/rtl-obfuscation-single/mapping.json \
  --metrics /tmp/rtl-obfuscation-single/metrics.json
```

## 多文件加密

先准备一个 `.f` 文件，每行写一个相对于 source root 的 SystemVerilog 文件。例如：

```text
rtl/alu.sv
rtl/top.sv
```

仓库中的 `rtl_samples/filelist.f` 可以直接用于示例：

```sh
mkdir -p /tmp/rtl-obfuscation-filelist
python -m rtl_obfuscator.rewrite encrypt-vnext \
  --filelist filelist.f \
  --source-root rtl_samples \
  --output-dir /tmp/rtl-obfuscation-filelist/gate \
  --map /tmp/rtl-obfuscation-filelist/mapping.json \
  --metrics /tmp/rtl-obfuscation-filelist/metrics.json
```

`--filelist` 和文件清单中的路径都应相对于 `--source-root`。

filelist 可以选择性地增加 `--top 顶层模块名`。此时，清单中的所有文件仍会按
`--category` 加密普通名称；只有 `--top` 依赖闭包内的跨模块名称，才能在同时得到
`--category` 和 `--abi-category` 明确授权后加密。清单中位于该闭包之外的跨模块名称不会
加密，`--top` 自身对外边界也始终保持不变。

例如，完整选择默认 13 类和其余 6 类时，使用：

```sh
--top your_top \
--category all --category modules --category ports --category interface
```

如果还要加密 top 闭包内允许变化的跨模块名称，需要再按照
[可加密类型表](docs/systemverilog_renaming_table.md)逐项添加对应的 `--abi-category`。

## Project-root 加密

project-root 模式会自动查找 `--top` 的依赖文件，因此必须提供顶层模块名：

```sh
mkdir -p /tmp/rtl-obfuscation-project
python -m rtl_obfuscator.rewrite encrypt-vnext \
  --project-root rtl_samples/example_fifo \
  --top fifo_top \
  --output-dir /tmp/rtl-obfuscation-project/gate \
  --map /tmp/rtl-obfuscation-project/mapping.json \
  --metrics /tmp/rtl-obfuscation-project/metrics.json
```

## 输出

- `--output-dir`：加密后的 SystemVerilog 文件目录。
- `--map`：本次加密的映射和执行报告。
- `--metrics`：本次加密的覆盖率报告。

这三个输出参数都必须提供，而且各自的目标路径必须尚不存在。重复运行时，请换用新路径，
或先自行处理旧输出。

可选择的加密对象见
[SystemVerilog 可加密类型表](docs/systemverilog_renaming_table.md)。开发和维护信息见
[项目结构](docs/project_structure.md)。

## 加密指令选项

完整帮助可以直接查看：

```sh
python -m rtl_obfuscator.rewrite encrypt-vnext --help
```

| 选项 | 是否必需 | 用法 |
| --- | --- | --- |
| `--input PATH` | 三选一 | 加密一个 `.sv` 文件；路径相对于 `--source-root`，也可使用绝对路径。 |
| `--filelist PATH` | 三选一 | 加密 `.f` 文件列出的多个文件；路径相对于 `--source-root`，也可使用绝对路径。 |
| `--project-root PATH` | 三选一 | 自动发现项目文件；使用时必须同时提供 `--top`，且不提供 `--source-root`。 |
| `--source-root PATH` | single/filelist 必需 | 单文件或 filelist 的源文件根目录。 |
| `--top NAME` | project-root 必需，single/filelist 可选 | 顶层模块名；filelist 提供后仍加密全部清单文件的普通名称，只把 ABI 授权限制在 top 闭包内，并保留 top 自身边界。 |
| `--include-dir PATH` | 可选，可重复 | 添加 include 目录。相对路径以 source root 为基准。 |
| `--define NAME[=VALUE]` | 可选，可重复 | 添加预处理宏，例如 `--define SYNTHESIS` 或 `--define WIDTH=32`。 |
| `--category NAME` | 可选，可重复 | 选择加密类型。未提供时使用默认类型；合法值见可加密类型表。 |
| `--abi-category NAME` | 可选，可重复 | 允许加密指定的跨模块名称；需要 `--top`，且该类型也必须出现在 `--category` 中。 |
| `--encryption-rate RATE` | 可选 | 加密比例，范围为大于 `0` 且不大于 `1`。 |
| `--name-length N` | 可选 | 新名称长度，最小为 `4`，默认值为 `20`。 |
| `--output-dir PATH` | 必需 | 加密文件输出目录；目标必须不存在，父目录必须存在。 |
| `--map PATH` | 必需 | 映射报告文件；目标必须不存在，父目录必须存在。 |
| `--metrics PATH` | 必需 | 覆盖率报告文件；目标必须不存在，父目录必须存在。 |
