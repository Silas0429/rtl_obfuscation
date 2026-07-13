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

第一版只支持：

- gold 和 gate 各一个 `.sv` 文件。
- 两个文件具有相同的 top module 名。
- top 的 port 名、方向和位宽保持一致。
- 允许内部变量、net、instance 等名称不同。
- Yosys `read_verilog -sv` 能读取全部语法。
- 设计能够由 `prep -flatten` 完整展开，不依赖外部 blackbox/library。
- 顺序逻辑使用两边一致的 clock、reset 和初始语义。

第一版不支持：

- top module 或 top port 重命名。
- 多文件 filelist、include directory、define、library 自动发现。
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

## 4. 内部 Yosys 流程

脚本固定执行：

1. `read_verilog -sv -formal` 读取 gold。
2. `prep -top <top> -flatten` 处理并展开 gold。
3. 将 top 改名为 `gold` 并 stash design。
4. 对 gate 执行相同处理，将 top 改名为 `gate`。
5. `equiv_make gold gate equiv` 建立等价检查模块。
6. `equiv_simple -seq 5` 执行 SAT 等价证明。
7. `equiv_induct -seq 5` 处理仍未证明的顺序等价点。
8. `equiv_status -assert` 保证任何未证明点都会使命令失败。

不得删除最后的 `-assert`，也不得仅根据日志中出现部分 `success` 判断通过。

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
