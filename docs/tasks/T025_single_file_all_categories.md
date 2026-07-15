# T025：扩展单文件全类别演示样例

- 状态：`ACCEPTED`
- 负责人：主 Agent
- 前置任务：T024 `ACCEPTED`

## 目标

扩展 `rtl_samples/11_supported_obfuscation.sv`，使单文件 `--category all` 真正覆盖全部 13 个默认 category：

- 保留现有 signals、parameters、enum_values、genvars、functions、tasks、arguments、generate_blocks、typedefs；
- 在同一 `.sv` 中补充 module instance、struct type/field 和 union type/field；
- 保持 sample 可解析、可 formal 验证、可解密恢复。

## 允许文件

- `rtl_samples/11_supported_obfuscation.sv`
- `tests/test_all_category_rewrite.py`
- `tests/test_debug_mode.py`
- `tests/test_supported_integration.py`
- `read.md`
- `rtl_samples/README.md`
- `docs/tasks/T025_single_file_all_categories.md`

## 验收

1. 单文件 `--category all` 的 mapping 包含 13 个 category，不再缺少 instances、struct_types、struct_fields、union_fields。
2. 更新后的固定 summary、mapping entries 和 metrics 与实际运行一致。
3. PySlang、Verible、Icarus 通过，Yosys formal 正例通过，功能变更负例仍失败。
4. 加密后通过 decrypt 字节级恢复。
5. 单文件自动 debug 继续生成 13 个 category 子目录。
6. 完整 unittest、`py_compile`、`git diff --check` 通过。

## 验收结果

- 单文件 `--category all` 实测：`{"files": 1, "mapping_entries": 33, "modified_tokens": 90}`。
  mapping 按固定顺序包含 signals、parameters、enum_values、genvars、functions、tasks、
  arguments、instances、generate_blocks、typedefs、struct_types、struct_fields、
  union_fields 共 13 类；其中新增 `u_helper`、`pair_t`/`payload_t`、结构体字段和联合体
  字段均有实际声明或引用。
- metrics 实测：changed lines `57/86`，symbols `33/33`，occurrences `90/90`，
  `plaintext_leakage_rate=0.0`，`effective_coverage=1.0`。
- 加密后 gate 的 PySlang diagnostics 为 0；Verible 和 Icarus 语法检查退出码为 0。
  Icarus 仅输出其既有 constant-select 提示，不是语法失败。
- 主 Agent 独立运行 Yosys formal：
  `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold rtl_samples/11_supported_obfuscation.sv --gate /tmp/t025_accept/gate.sv --top sample11_supported_obfuscation`
  退出码为 0，结果为 `{"formal_equivalence":"pass","seq":5,"top":"sample11_supported_obfuscation"}`。
- decrypt 输出与 gold 字节级一致（两者均为 2796 bytes）。
- 单文件自动 debug 继续生成 13 个 category 子目录；更新后的专项测试验证每类摘要和
  gate range。完整回归为 `Ran 33 tests`、`OK`；其中既有 formal 正例和功能变更负例均
  保持预期结果。
- `py_compile` 和 `git diff --check` 通过。

## 执行记录

- 2026-07-15：主 Agent 扩展样例、同步测试和样例说明；新增 helper module instance、
  packed struct/union 及其真实引用。
- 2026-07-15：主 Agent 独立完成前端、formal、decrypt 和完整回归验收，任务设置为
  `ACCEPTED`。本任务未由子 Agent 提交或推送。
