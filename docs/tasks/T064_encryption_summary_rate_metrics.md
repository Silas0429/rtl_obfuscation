# T064：修正 encryption_summary.txt 统计口径

- 状态：ACCEPTED
- 合同版本：1.0
- 设计时间：2026-07-28
- 设计负责人：主 Agent
- 前置任务：T063 `ACCEPTED`
- 起始 HEAD：`831bf6e`
- 任务类型：加密摘要统计修正

## 1. 目标

修正 `encryption_summary.txt` 的统计内容。当前“加密率”错误地使用了输入 target rate；
必须改为实际加密行数除以总代码行数，即 metrics 的 `affected_lines.rate`。

## 2. 固定输出

固定八行、固定顺序：

```text
加密率：<metrics.affected_lines.rate>
实际加密行数：<metrics.affected_lines.changed>
总代码行数：<metrics.effective_lines.total>
实际加密名称数：<metrics.symbols.renamed>
可加密名称数：<metrics.symbols.eligible>
加密覆盖率：<metrics.effective_coverage>
加密类型数：<实际 rename category 数>
加密类型：<category>, <category>, ...
```

- 所有数值直接来自同一次 encryption 的 metrics，不能从命令行 target rate 推导“加密率”。
- 加密类型只统计实际产生 rename record 的去重 category，顺序按 canonical category。
- 无实际加密时类型数为 `0`，类型内容为空；summary 仍必须生成。

## 3. 验收边界

必须覆盖：

1. no-rate 输出的加密率等于 `affected_lines.rate`，不是固定 `1.0`；
2. `--encryption-rate 0.35` 输出的加密率仍等于实际 affected-line rate，而不是 `0.35`；
3. 实际加密行、总代码行、实际/可加密名称、effective coverage 与 metrics 逐项一致；
4. 默认/显式 map 与 metrics、single/filelist/project 输出路径和 CSV 行为不变；
5. T063 相关测试、常规回归、py_compile、diff check 继续通过。

本任务只修正摘要统计展示，但 encryption 命令仍产生 rewritten RTL；必须独立复跑 compact
Formal 正例和单个 `~` 负例。正例必须 `formal_equivalence=pass`，负例必须非零并包含
`unproven` 与 `equiv_status -assert`。不得运行 RISC-V-Vector Formal。

## 4. 允许修改

```text
README.md
rtl_obfuscator/rewrite.py
tests/test_cli_vnext_encryption.py
tests/test_public_cli.py
docs/tasks/T064_encryption_summary_rate_metrics.md
```

不得修改 RTL fixture、mapping/rate/metrics 核心语义、restore 核心校验、Formal 脚本或历史
任务记录。

## 5. 状态要求

- 完成实现与验收记录后设置 `READY_FOR_REVIEW`；
- `ACCEPTED` 由主 Agent 独立验收后设置。

## 6. 执行记录与主 Agent 验收

- 修改文件：

  ```text
  README.md
  rtl_obfuscator/rewrite.py
  tests/test_cli_vnext_encryption.py
  tests/test_public_cli.py
  docs/tasks/T064_encryption_summary_rate_metrics.md
  ```

- `encryption_summary.txt` 已固定为八行：实际加密率、实际加密行数、总代码行数、实际加密名称数、
  可加密名称数、加密覆盖率、实际加密类型数和实际加密类型。
- 实际加密率取 `metrics.affected_lines.rate`，不再取命令行目标加密率或名称覆盖率。
- 定向回归：33/33 通过，exit code 0；覆盖 no-rate、指定加密率、默认/显式报告路径以及摘要逐项一致性。
- 常规全量回归：192/192 通过，显式排除 `tests.test_risc_v_vector_project_root`。
- `py_compile`：exit code 0；`git diff --check HEAD`：通过。
- compact Formal 正例：exit code 0，JSON `formal_equivalence=pass`。
- compact Formal 功能负例：仅在 gate 中插入一个 `~`；catalog/top-overlay strict compile 均为 0/0，
  Formal exit code 1，输出包含 `unproven` 和 `equiv_status -assert`。
- 未运行 RISC-V-Vector Formal。
- 结论：T064 合同全部满足，主 Agent 已将状态设为 `ACCEPTED`。
