# T089：同步 `.v/.vh` 后缀支持文档

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：主 Agent
- 前置任务：T088 `ACCEPTED`，提交 `360577c`
- 任务类型：文档一致性同步；不修改 RTL、解析器、mapping、rewrite、restore 或 Formal 行为
- Formal verification：`N/A`；本任务不产生 rewritten RTL

## 1. 单一目标

将当前有效的三入口架构和 SourceSet 设计文档同步到已验收的后缀合同：

- source unit：小写 `.sv`、`.v`；
- included physical header：小写 `.svh`、`.vh`；
- 四种后缀继续使用同一 PySlang SystemVerilog semantic frontend，不切换 strict legacy-Verilog parser；
- header 进入物理清单和恢复审计，但不进入 `compile_order` 或 canonical `design.f`。

## 2. 允许修改

- `docs/development/architecture/three_mode_refactor_plan.md`；
- `docs/development/process/refactor_next_sourceset_task.md`；
- `docs/systemverilog_renaming_table.pdf`；
- `docs/tasks/T089_documentation_suffix_sync.md`。

历史任务合同（包括 T039、T078、T087、T088）不修改；当前 README、Formal、重命名表 Markdown、
项目结构和 future-work 文档已由 T088 同步，本任务不重复改写。只补发仍停留在旧版本的重命名表 PDF。

## 3. 验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t088_verilog_suffix tests.test_source_set -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rtl_files.py rtl_obfuscator/source_set.py
git diff --check HEAD
```

此外必须检查两份目标文档不再把 `.sv/.svh` 描述为唯一后缀，并明确 `.sv/.v` source 与
`.svh/.vh` header 分类。

## 4. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 360577c
changed_files: docs/development/architecture/three_mode_refactor_plan.md; docs/development/process/refactor_next_sourceset_task.md; docs/systemverilog_renaming_table.pdf; docs/tasks/T089_documentation_suffix_sync.md
commands: `conda run -n rtl_obfuscation python -m unittest tests.test_t088_verilog_suffix tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rtl_files.py rtl_obfuscator/source_set.py`; `git diff --check HEAD`; target-document stale-suffix scan
results: unittest exit 0, Ran 19 tests, OK; py_compile exit 0; diff check exit 0; target documents explicitly classify `.sv/.v` source units and `.svh/.vh` included headers; regenerated PDF has 2 A4 pages, extractable `.v/.vh/SystemVerilog` text, and rendered pages visually pass with no clipping or overlap
formal_verification: N/A
deviation: 首轮静态检查发现 `docs/systemverilog_renaming_table.pdf` 仍是 T088 前生成物；按文档同步范围补发该 PDF，并追加渲染验收。
review_request: READY_FOR_REVIEW；主 Agent 已完成独立复核。
```

## 5. 主 Agent 独立验收

```text
acceptance_status: ACCEPTED
acceptance_head: 360577c
allowed_files: PASS；仅修改两份当前设计文档、同步后的重命名表 PDF 和本任务单；历史任务合同未修改。
independent_commands: `conda run -n rtl_obfuscation python -m unittest tests.test_t088_verilog_suffix tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rtl_files.py rtl_obfuscator/source_set.py`; `git diff --check HEAD`; bundled pypdf suffix/A4 check
independent_results: unittest exit 0, Ran 19 tests, OK; py_compile exit 0; diff check exit 0; PDF 2 pages, `.v/.vh/SystemVerilog` text present, A4 dimensions valid
visual_review: `docs/systemverilog_renaming_table.pdf` 2 pages rendered and inspected; no clipping, overlap, black blocks, or unreadable table columns
formal_verification: N/A；文档同步不产生 rewritten RTL
decision: ACCEPTED
```
