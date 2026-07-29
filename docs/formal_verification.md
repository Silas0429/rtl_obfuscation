# 加密后的 Formal 功能验证

加密工具只替换 SystemVerilog 名称。Formal 验证用于确认“原始 RTL”和“加密后的 RTL”在相同输入下功能等价。
它是独立的检查工具，不是加密或解密命令的必需参数，也不会生成加密结果或恢复源码。

## 什么时候需要运行

建议在以下情况运行一次：

- 第一次给某个 RTL 项目加密后；
- 修改了 `--category`、`--top` 或 `--encryption-rate` 后；
- 需要向下游交付一份功能等价的加密 RTL 时。

加密命令本身已经检查名称替换、严格编译、映射报告和恢复结果。Formal 进一步检查改名没有改变电路功能。

## 准备条件

需要在当前 Python 环境中可以运行项目命令，并且系统中可以找到 Yosys：

```sh
python -c "import pyslang; print(pyslang.__version__)"
yosys -V
```

如果服务器无法联网安装 PySlang，请先阅读
[PySlang 源码编译与离线部署指南](pyslang源码编译与离线部署指南.md)。

Formal 输入必须满足：

- 原始 RTL 与加密 RTL 使用相同的 top module 名称；
- top 的端口和端口方向保持一致；
- 多文件工程使用相同的编译顺序和等价的宏/include 设置；
- filelist 中的路径相对于各自的 `--gold-root` 或 `--gate-root` 可找到。

## 多文件项目：推荐命令

加密时保留原始 filelist，并让工具在输出目录生成加密后的 `design.f`：

```sh
python rtl_encrypt.py \
  --filelist <原始项目>/design.f \
  --source-root <原始项目> \
  --top <top_module> \
  --output-dir <工作目录>/gate
```

然后运行：

```sh
python scripts/formal_equivalence.py \
  --gold-filelist <原始项目>/design.f \
  --gold-root <原始项目> \
  --gate-filelist <工作目录>/gate/design.f \
  --gate-root <工作目录>/gate \
  --top <top_module> \
  --seq 5
```

`--seq 5` 是默认的时序证明深度；如果项目需要更深的时序展开，可以改为更大的正整数。

## 单文件：简化命令

单文件加密结果可以直接比较原始文件和 gate 文件：

```sh
python rtl_encrypt.py \
  --input <原始目录>/design.sv \
  --source-root <原始目录> \
  --output-dir <工作目录>/gate

python scripts/formal_equivalence.py \
  --gold <原始目录>/design.sv \
  --gate <工作目录>/gate/rtl/design.sv \
  --top <top_module> \
  --seq 5
```

如果输出目录中的文件名或目录结构不同，以加密命令生成的实际 gate 文件路径为准。

## 如何判断结果

成功时命令退出码为 `0`，最后会输出一行 JSON，其中包含：

```json
{"formal_equivalence": "pass", "top": "<top_module>"}
```

只有同时满足退出码为 `0` 且 `formal_equivalence` 为 `pass`，才表示这次 Formal 验证通过。

失败时命令退出码非 `0`。常见原因包括：

- 原始 RTL 与 gate 的 top 或端口不一致；
- Yosys 无法解析项目使用的 SystemVerilog 语法；
- 加密范围导致了实际的功能差异；
- 时序证明深度不足。

失败后应检查加密命令的终端错误、`mapping.json`、`metrics.json` 和生成的 gate，不要把失败结果作为可交付 RTL。

## 负例测试说明

项目测试会从实际 gate 复制一份文件，只在功能表达式中加入一个 `~`，再确认 Formal 以非零状态失败。
这只是验证 Formal 门禁确实能发现功能变化的测试方法；正常使用时不要修改 gate 后再交付。

## RISC-V-Vector 专项

RISC-V-Vector 是项目内部的专项发布验收，不属于普通用户的日常加密验证流程。普通项目只需按本页的单文件或多文件命令检查自己的 top；专项脚本不作为用户入口。
