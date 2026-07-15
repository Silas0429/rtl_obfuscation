# T021：交付文档收敛

- 状态：`ACCEPTED`
- 负责人：主 Agent
- 前置任务：T020 `ACCEPTED`

## 目标

将面向使用者的文档收敛为四个明确入口：

1. 根目录 `read.md`：项目结构、安装、基本操作、实现机制和能力边界；
2. `docs/systemverilog_renaming_table.md`：当前已实现 category 的语义表；
3. `docs/formal_verification.md`：PySlang 前端、Yosys formal 和解密验证流程；
4. `docs/future_work.md`：未实现能力和已知问题。

`docs/tasks/` 保留历史合同，不用作用户使用说明。

## 约束

- 删除 `docs/tasks/` 之外重复、过时的交付/设计/交接文档。
- 用户文档中的 Python 命令直接以 `python` 开头，不使用 `conda run` 包装。
- PySlang 是主前端；Yosys 负责形式等价；Verible 和 Icarus 仅作可选附加前端检查。
- 文档只描述当前已验收行为；未实现项放入 `future_work.md`。
- 明确顶层 interface port 不属于当前可靠交付边界。

## 允许文件

- `read.md`
- `AGENTS.md`
- `docs/*.md`
- `docs/tasks/T020_example_fifo_per_file_mapping.md`
- `docs/tasks/T021_documentation_consolidation.md`
- `docs/tasks/README.md`
- `rtl_samples/README.md`

## 验收

1. `docs/tasks/` 之外不再存在重复的旧设计或交接文档。
2. 公开文档不包含 `conda run -n rtl_obfuscation`。
3. 不存在指向已删除文档的有效引用。
4. FIFO 完整命令、`77/292`、per-file mapping、debug、decrypt 和 formal 使用说明保留。
5. `python -m unittest discover -s tests -v` 通过30项回归。
6. `git diff --check` 通过。

## 验收结果

- 公开文档已收敛为根目录 `read.md`、重命名表、验证流程和未来事项；
  `docs/tasks/` 之外的文档由 9 份约 2190 行减少为 3 份约 281 行，
  根目录使用说明为 302 行。
- 公开文档中无 `conda run -n rtl_obfuscation`，无指向已删除文档的引用。
- 按 `read.md` 实际重跑：FIFO 完整加密 `77/292`，parameter debug `9/51`，
  单文件 `23/63`，PySlang `errors=0`，metrics coverage `1.0`、leakage `0.0`，
  decrypt 四文件字节一致。
- 文档任务本身不产生新 gate，`formal_verification: N/A`。为验证使用说明，
  独立执行 FIFO Yosys 命令并得到 `formal_equivalence=pass`。
- `python -m unittest discover -s tests -v` 实际 `Ran 30 tests`、`OK`；
  `py_compile` 和 `git diff --check` 通过。
- 主 Agent 验收：`ACCEPTED`。
