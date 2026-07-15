# Yosys 形式等价验证流程

## 1. 目标

本流程使用 Yosys 比较原始 SystemVerilog（gold）与重命名后的 SystemVerilog（gate），证明重命名没有改变可观察 RTL 行为。

当前已测试环境：

```text
Yosys 0.53
Conda environment: rtl_obfuscation
```

可复用入口为：

```text
scripts/formal_equivalence.py
```

## 2. 当前输入边界

当前支持：

- gold 和 gate 各一个 `.sv` 文件，或者各一个只列出显式 `.sv` 相对路径的 filelist。
- 两个文件具有相同的 top module 名。
- top 的 port 名、方向和位宽保持一致。
- 允许内部变量、net、instance 等名称不同。
- Yosys `read_verilog -sv` 能读取全部语法。
- 设计能够由 `prep -flatten` 完整展开，不依赖外部 blackbox/library。
- 静态 memory 能由 `memory_map -formal` 展开为可进入 equivalence/SAT 的逻辑。
- 顺序逻辑使用两边一致的 clock、reset 和初始语义。

当前不支持：

- top module 或 top port 重命名。
- 嵌套 filelist、include directory、define、library 自动发现。
- macro、DPI、class、动态 testbench 结构。
- Yosys frontend 不接受的 SystemVerilog 语法。
- 自动生成 assumption、reset sequence 或 blackbox model。

遇到边界外设计时任务应记录 `BLOCKED`，不得跳过 formal 或把失败改写成通过。

## 3. 执行命令

从仓库根目录运行：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold path/to/original.sv \
  --gate path/to/renamed.sv \
  --top unchanged_top_module
```

默认顺序证明深度为 5；仅在任务单明确要求时调整：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold path/to/original.sv \
  --gate path/to/renamed.sv \
  --top unchanged_top_module \
  --seq 5
```

多文件模式显式给出两侧 filelist 和 source root：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist path/to/gold/design.f \
  --gold-root path/to/gold \
  --gate-filelist path/to/gate/design.f \
  --gate-root path/to/gate \
  --top unchanged_top_module \
  --seq 5
```

## 4. 内部 Yosys 流程

脚本固定执行：

1. `read_verilog -sv -formal` 读取 gold。
2. `prep -top <top> -flatten` 处理并展开 gold。
3. `memory_map -formal` 将静态 memory 对称展开为 formal 可处理的逻辑。
4. `opt_clean` 清理 memory mapping 产生的无用单元和连线。
5. 将 top 改名为 `gold` 并 stash design。
6. 对 gate 严格执行相同的 `prep`、`memory_map -formal` 和 `opt_clean`，然后将 top
   改名为 `gate` 并 stash design。
7. `equiv_make gold gate equiv` 建立等价检查模块。
8. `hierarchy -top equiv` 建立 equivalence hierarchy。
9. `equiv_struct -icells` 按结构和内部 cell 对应关系补充因随机改名丢失的 equivalence。
10. `equiv_simple -seq 5` 执行 SAT 等价证明。
11. `equiv_induct -seq 5` 处理仍未证明的顺序等价点。
12. `equiv_status -assert` 保证任何未证明点都会使命令失败。

单文件和多文件模式必须生成同一套核心 Yosys pass，不得只修复其中一条路径。gold/gate
两侧的预处理必须完全对称。不得删除最后的 `-assert`，也不得仅根据日志中出现部分
`success` 判断通过。

## 5. 输出契约

成功时退出码为 0，stdout 只输出一行 JSON：

```json
{
  "formal_equivalence": "pass",
  "gate": "/absolute/path/to/gate.sv",
  "gold": "/absolute/path/to/gold.sv",
  "seq": 5,
  "top": "unchanged_top_module"
}
```

失败时退出码非 0，Yosys 日志写入 stderr。只有退出码为 0 且 JSON 中 `formal_equivalence` 为 `pass` 才算通过。

## 6. 在任务流程中的使用

- T001、T002 只输出映射或 source range，不产生改写 RTL，formal 状态固定记录为 `N/A`，并注明原因。
- 从 T003 开始，任何产生 gate RTL 的任务都必须运行本流程。
- 子 Agent 自测时运行一次并把命令、JSON、gold/gate/top 写入任务单。
- 主 Agent 验收时必须独立重跑，不能只引用子 Agent 的结果。
- formal 失败时任务不能进入 `READY_FOR_REVIEW` 或 `ACCEPTED`。
- 修改 formal 流程的任务必须同时提供等价正例和非等价负例；正例必须退出 0 并输出 PASS
  JSON，负例必须非零退出。identity comparison 只能用作诊断，不能替代 transformed gate。

## 7. 已验证基线

等价正例：`gate.sv` 只把内部寄存器 `count_register` 改为 `Q7m2_xAa`。

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold tests/formal/variable_rename/gold.sv \
  --gate tests/formal/variable_rename/gate.sv \
  --top formal_variable_rename
```

结果：退出码 0，`formal_equivalence=pass`。

非等价负例：`non_equivalent.sv` 除改名外还把计数增量从 1 改为 2。

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold tests/formal/variable_rename/gold.sv \
  --gate tests/formal/variable_rename/non_equivalent.sv \
  --top formal_variable_rename
```

结果：退出码 1，`equiv_status -assert` 报告 4 个未证明的 `$equiv` cells。该负例证明流程不会把明显的行为改变误判为通过。

## 8. T020 多文件 memory/state 基线

T020 使用 `rtl_samples/example_fifo/design.f` 的四文件 FIFO，完整重命名会改动内部 state、
status signal 和 RAM 名称。固定正向命令见 T020 任务单；必须得到退出码 0 和
`formal_equivalence=pass`。

专项测试还必须在临时目录基于有效 gate 生成非等价 FIFO 变体，把计数增量从 1 改为 2。
该负例必须非零退出并由 `equiv_status -assert` 报告未证明单元。临时变体不得写回或替换
冻结 gold。正负结果共同证明 memory mapping 与 structural matching 能处理合法重命名，
但不会把真实行为变化误判为等价。
