# T065：删除无法准确解释的摘要名称统计

- 状态：ACCEPTED
- 合同版本：1.0
- 设计时间：2026-07-28
- 设计负责人：主 Agent
- 前置任务：T064 `ACCEPTED`
- 起始 HEAD：`1f6651f`
- 任务类型：用户摘要输出修正

## 1. 目标

`metrics.json` 当前没有与用户定义完全一致的“按当前替换类型可加密名称数”和加密率限制下实际加密名称数。
因此不在 `encryption_summary.txt` 中展示容易误导的名称计数和名称覆盖率，只保留可以直接解释的行级统计和实际加密类型。

不修改 mapping、metrics 的核心计算，不新增字段，不改变加密选择和 RTL 输出。

## 2. 固定输出

`encryption_summary.txt` 固定为五行、固定顺序：

```text
加密率：<metrics.affected_lines.rate>
实际加密行数：<metrics.affected_lines.changed>
总代码行数：<metrics.effective_lines.total>
加密类型数：<实际产生 rename record 的 category 数>
加密类型：<category>, <category>, ...
```

## 3. 允许修改

```text
README.md
rtl_obfuscator/rewrite.py
tests/test_cli_vnext_encryption.py
tests/test_public_cli.py
docs/tasks/T065_encryption_summary_available_name_counts.md
```

不得修改 mapping/metrics 核心实现、restore、Formal 脚本、RTL fixture 或历史任务记录。

## 4. 验收要求

- no-rate 与指定加密率的 summary 均为固定五行；
- 加密率仍等于实际 `affected_lines.rate`，不能使用 target rate；
- 行数和实际加密类型与同一次 encryption 的 metrics/mapping 一致；
- 定向测试、常规回归、`py_compile`、`git diff --check HEAD` 通过；
- 因命令仍产生 rewritten RTL，独立复跑 compact Formal 正例和单个 `~` 功能负例；正例必须
  `formal_equivalence=pass`，负例必须非零且含 `unproven`、`equiv_status -assert`；
- 不运行 RISC-V-Vector Formal。

## 5. 执行记录与主 Agent 验收

- 修改文件：

  ```text
  README.md
  rtl_obfuscator/rewrite.py
  tests/test_cli_vnext_encryption.py
  tests/test_public_cli.py
  docs/tasks/T065_encryption_summary_available_name_counts.md
  ```

- `encryption_summary.txt` 已从八行收敛为五行，删除“实际加密名称数”“可加密名称数”和“加密覆盖率”。
- 实际加密率仍取 `metrics.affected_lines.rate`，行数和加密类型仍逐项对应同一次 encryption 的
  metrics/mapping。
- 定向回归：33/33 通过，exit code 0。
- 常规全量回归：192/192 通过，显式排除 `tests.test_risc_v_vector_project_root`。
- `py_compile`：exit code 0；`git diff --check HEAD`：通过。
- compact Formal 正例：exit code 0，`formal_equivalence=pass`。
- compact Formal 功能负例：只插入一个 `~`；catalog/top-overlay strict compile 均为 0/0，
  Formal exit code 1，包含 `unproven` 和 `equiv_status -assert`。
- 未运行 RISC-V-Vector Formal。
- 结论：T065 合同全部满足，主 Agent 已将状态设为 `ACCEPTED`。
