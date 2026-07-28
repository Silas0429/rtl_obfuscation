# T062：增加可读加密摘要文件

- 状态：ACCEPTED
- 合同版本：1.0
- 设计时间：2026-07-28
- 设计负责人：主 Agent
- 前置任务：T061 `ACCEPTED`
- 起始 HEAD：`8da4f78`
- 任务类型：公共加密输出增强

## 1. 目标

每次 public/internal `encrypt-vnext` 成功后，在加密输出目录额外生成两个面向用户的可读文件：

- `mapping_table.csv`：每个实际执行的名称替换一行，列为
  `文件名`、`模块名`、`加密类型`、`原名`、`替换后名`。
- `encryption_summary.txt`：记录加密率、总代码行数、替换行数、总替换名称数、替换类型数和
  实际发生替换的加密类型。

两个文件固定写入 `<output-dir>`，不受 `--map`、`--metrics` 显式路径影响。原有
`mapping.json`、`metrics.json` 的默认位置与显式路径行为不变。

## 2. 固定格式

### 2.1 mapping_table.csv

- UTF-8 编码，首行为中文列名，换行符固定为 `\n`。
- 只记录 `action == "rename"` 的 mapping record，每条 record 一行，不按 occurrence 重复展开。
- 行顺序与 mapping.json 中 `mapping.records` 的顺序一致，保证 deterministic。
- 字段来源：
  - 文件名：record declaration 的 file；
  - 模块名：从 record owner_module 的源码范围解析出的可读 owner 名称；`$unit` 等无模块
    作用域保留原值，不输出内部 `module:file:start:end` 定位串；
  - 加密类型：record category；
  - 原名：record original_name；
  - 替换后名：record renamed_name。
- 没有实际替换时仍生成只有表头的 CSV。

### 2.2 encryption_summary.txt

使用固定顺序和中文标签，每行一个字段：

```text
加密率：<decimal>
总代码行数：<integer>
替换行数：<integer>
总替换名称数：<integer>
替换类型数：<integer>
加密类型：<category>, <category>, ...
```

- 未提供 `--encryption-rate` 时加密率为 `1.0`；提供时记录 rate-selection 的 target。
- 总代码行数取 metrics `effective_lines.total`。
- 替换行数取 metrics `affected_lines.changed`。
- 总替换名称数为 mapping 中实际 rename record 数。
- 替换类型数和加密类型只统计实际出现 rename record 的去重 category，顺序按
  `CANONICAL_CATEGORIES`，没有实际替换时类型数为 `0`，加密类型为空。

## 3. 原子性与兼容性

- 两个新文件必须在 staging 中生成，随 gate 一起原子发布；任一生成或发布失败不得留下
  gate、mapping、metrics、CSV 或 TXT 的半成品。
- `--map`、`--metrics` 可分别显式写到 output-dir 外；两个新文件仍只写入 output-dir。
- restore gate file-set 校验允许这两个已知派生附件存在，也继续接受 T061 以前没有这两个附件的
  旧 vNext gate；未知额外文件仍 fail-closed。
- direct restore 不使用 CSV/TXT 作为恢复输入，不改变 mapping、metrics、manifest、range 或
  hydration 校验。

## 4. 测试边界

必须覆盖：

1. 单文件默认 rate、filelist/project-root 全部加密、rate 选择四种公共输出组合中至少包含
   no-rate 与 rate；
2. CSV 表头、字段值、rename 行数、行顺序与 mapping record 对齐；
3. TXT 六项字段、no-rate 的 `1.0`、rate target、metrics 数值和实际 category 去重；
4. 默认/显式 map 与 metrics 不改变两个新文件的位置；
5. 两个文件内容 deterministic；
6. 新 gate 可被 public decrypt 直接恢复，旧 gate 无新附件仍可恢复；
7. orchestration、写入和发布失败时无部分输出；
8. public README 说明四个加密输出文件及其用途。

## 5. 允许修改

```text
README.md
rtl_obfuscator/rewrite.py
rtl_obfuscator/restore_vnext.py
tests/test_cli_vnext_encryption.py
tests/test_public_cli.py
docs/tasks/T062_readable_encryption_artifacts.md
```

不得修改 RTL fixture、mapping/rate/metrics 核心语义、Formal 脚本或历史任务记录。

## 6. 验收命令

内部环境统一使用：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_cli_vnext_encryption tests.test_public_cli tests.test_restore_vnext \
  tests.test_vnext_product_surface -v
conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py \
  tests/test_cli_vnext_encryption.py tests/test_public_cli.py
git diff --check HEAD
```

本任务仍需独立复跑现有 compact Formal 正例和插入一个 `~` 的固定负例；正例必须
`formal_equivalence=pass`，负例必须非零并包含 `unproven` 与 `equiv_status -assert`。不得运行
RISC-V-Vector Formal。

## 7. 状态要求

- 实现开始前保持本任务为 `IN_PROGRESS`。
- 完成后记录修改文件、完整命令、实际结果和未覆盖边界，状态才能设为
  `READY_FOR_REVIEW`。
- `ACCEPTED` 由主 Agent 独立验收后设置。

## 8. 执行记录与主 Agent 验收

- 实现未修改 RTL fixture、mapping/rate/metrics 核心语义、Formal 脚本或历史任务记录。
- 修改文件：

  ```text
  README.md
  rtl_obfuscator/rewrite.py
  rtl_obfuscator/restore_vnext.py
  tests/test_cli_vnext_encryption.py
  tests/test_public_cli.py
  docs/tasks/T062_readable_encryption_artifacts.md
  ```

- 定向测试：31/31 通过，exit code 0。
- 常规全量回归：190/190 通过，显式排除 `tests.test_risc_v_vector_project_root`。
- `py_compile`：exit code 0。
- `git diff --check HEAD`：通过。
- README FIFO smoke 在 `/tmp/t062-public.tSZYsQ`：
  - 默认 public project 命令生成 `mapping.json`、`metrics.json`、`mapping_table.csv` 和
    `encryption_summary.txt`；
  - CSV 头为五个约定中文列，模块名显示为 `fifo_ctrl`、`fifo_if` 等可读名称；
  - no-rate summary 为 `1.0`、219 总代码行、156 替换行、67 替换名称、18 个实际替换类型；
  - 新 gate 通过 public decrypt 直接恢复，4 个 RTL 文件 byte-identical。
- rate smoke 使用 `--encryption-rate 0.35`：TXT 首行准确记录 `加密率：0.35`，并保持其它
  统计与 metrics/mapping 一致。
- 默认/显式 map 与 metrics 的输出位置测试通过；两个新文件始终位于 output-dir。
- 写入失败、orchestration 失败和发布失败均未留下部分输出；旧 gate（没有两个新附件）仍可
  被 restore，未知额外 gate 文件仍被拒绝。
- Formal actual project gate 在 `/tmp/t062-formal.3COsif`：
  - 正例 exit 0，`formal_equivalence=pass`；
  - 负例只插入一个 `~`，catalog/top-overlay strict compile 均为 0/0；
  - 负例 exit 1，包含 `unproven` 与 `equiv_status -assert`。
- 未运行 RISC-V-Vector Formal。
- 结论：T062 合同全部满足，主 Agent 已将状态设为 `ACCEPTED`。
