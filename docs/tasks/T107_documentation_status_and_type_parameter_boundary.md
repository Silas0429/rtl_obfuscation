# T107：项目状态与 aggregate type-parameter 边界文档审计

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 实现负责人：主 Agent（文档审计，不启动实现子 Agent）
- 前置任务：T106 已 `ACCEPTED`
- 任务类型：文档/状态审计
- 起始 HEAD：`950be8e249450c6e4e324c9a2b7d43b8d4efb85b`

## 1. 单一目标

暂停产品修改，审核并同步当前公开说明、能力边界、开发者结构和 StCache 稳定化记录；准确保存
T106 之后的服务器实测事实：PySlang 已完成 StCache filelist compile/elaborate，但 `struct` mapping
仍会把 `SyntaxKind.TypeAssignment` 的类型参数 alias 当成物理 aggregate typedef，因而原子拒绝。

本任务只修正文档，不改变加密、解密、SourceSet、SymbolGraph、mapping、rewrite、CLI、测试、RTL
fixture 或 Formal 行为。

## 2. 固定事实

1. 当前产品提交为 `950be8e [FIX] Bind aggregate type references semantically`；T106 compact 合同已
   `ACCEPTED`，但不能替代 StCache 外部工程验收。
2. StCache `signals` 已报告 `PASS_FULL`，rename 3183、preserve 0、unsupported 0；strict compile 与
   byte-identical restore 通过，尚无 StCache actual-gate Formal。
3. StCache `ports` 已报告 `PASS_PARTIAL`，rename 2636、preserve 587、unsupported 18；18 个
   `macro_origin_conflict` 为两个 assertion 宏正文中的 `clk` / `rst_n`，本任务不处理。
4. StCache 完整 `interface` 仍因 interface instance array 和 category 隔离边界原子拒绝；本任务不处理。
5. T106 后服务器重跑 `--category struct`：SourceSet 147 个 source、compile order 154、PySlang
   semantic nodes 329758；mapping 在 `StChReqTagRw.sv:119` 的 `req_icmd_if_t req_icmd` 原子拒绝。
6. 该引用语义目标是 `StChReqTagRw.sv:46` 的 `TypeAssignment` 类型参数；真正物理
   `typedef struct req_icmd_if_t` 位于 `StChReqPath.sv:264`。`TypeAliasType.isStruct=True` 只说明
   canonical shape，不等于目标本身是物理 aggregate typedef 声明。
7. 当前公开 `parameters` 类不重命名 module type parameter；选择 `parameters` 时，T071 的既有边界是
   owner 安全保留。未来若修复 struct/union collector，必须按源码声明种类区分 physical typedef 与 type
   parameter；只选择 `struct` 时 type parameter 不得进入 aggregate graph，也不得名称匹配或
   canonical-type 回退。本任务只记录该边界，不授权实现。

## 3. 必须交付

1. README 明确 PySlang compile/elaborate 成功只证明输入可编译；selected symbol 到物理 token 的唯一映射
   仍是发布 gate 的独立条件。保持 filelist-first，不把开发诊断堆进快速开始。
2. SystemVerilog 类型表纠正 `parameters`、`struct_types` 的实际边界，并同步 PDF。
3. StCache 稳定化记录更新到当前产品提交和最新服务器结果，严格区分 compact accepted、外部
   `PASS_*`、external `REFUSED_ATOMIC` 与 Formal 证据。
4. future work、project structure 和架构索引记录同一根因与未来设计约束；不得把 future work 写成
   已授权实现或已支持能力。
5. T106 历史合同只追加 post-acceptance 外部观察，不改写当时验收结论。
6. README.pdf 与类型表 PDF 从本轮 Markdown 同步生成，文本可提取、A4、全页渲染无裁切、重叠、黑块
   或缺字。

## 4. 明确不包含

- 不修改 Python、测试、RTL、fixture、filelist、CLI、category、mapping schema 或 Formal 流程；
- 不实现 type-parameter normalization、interface array、port macro conflict 或其他兼容层/fallback；
- 不运行加密、HDL、Formal、RISC-V-Vector 或 blanket test discovery；
- 不修改历史任务的验收状态，不创建下一张实现任务；
- 不宣称 StCache struct/union、interface 或全部默认类别已稳定支持。

## 5. 允许修改文件

```text
README.md
README.pdf
docs/systemverilog_renaming_table.md
docs/systemverilog_renaming_table.pdf
docs/development/project_structure.md
docs/development/future_work.md
docs/development/README.md
docs/development/architecture/README.md
docs/development/architecture/stcache_core_category_stability.md
docs/tasks/T106_semantic_type_reference_binding.md
docs/tasks/T107_documentation_status_and_type_parameter_boundary.md
```

除此之外不得修改；PDF 生成器、渲染图和日志只放在 `/private/tmp`。

## 6. 验收命令

1. 公开文档目标测试：

   ```sh
   conda run -n rtl_obfuscation python -m unittest \
     tests.test_public_cli.PublicCliTests.test_readme_and_type_table_are_user_facing_and_consistent \
     tests.test_t096_public_frontend_input_modes.T096PublicFrontendInputModesTests.test_help_and_documents_are_filelist_first \
     -v
   ```

2. 状态事实、禁用误述和全部 Markdown 本地链接检查：使用 Conda Python 检查 README、类型表、
   StCache、future work、project structure、T106/T107 的冻结关键词，要求不存在 broken local link，
   并输出 `documentation_status_and_links=pass`。
3. 使用 PDF 技能运行时读取 README.pdf 与类型表 PDF，要求 A4、文本可提取并包含本轮边界关键词；
   随后用 Poppler 渲染全部页面并逐页检查。
4. `git diff --check HEAD`。
5. 使用 Conda Python 检查 Git 修改集合精确等于第 5 节允许文件，且 T107 顶部状态为
   `READY_FOR_REVIEW`；输出 `t107_ready_for_review=pass`。

## 7. Formal verification

```text
formal_verification: N/A
reason: T107 only updates documentation and synchronized PDFs; it produces no rewritten RTL
```

## 8. 执行记录

status: READY_FOR_REVIEW
starting_head: `950be8e249450c6e4e324c9a2b7d43b8d4efb85b`
start_time: 2026-08-26 Asia/Shanghai
first_action: 冻结 docs-only allowlist；审阅公开工作流、能力表、项目结构、future work、StCache 状态、
T071/T079/T105/T106 与 PDF 同步历史；未修改产品代码或测试。
changed_files: `README.md`、`README.pdf`、`docs/systemverilog_renaming_table.md`、
`docs/systemverilog_renaming_table.pdf`、`docs/development/project_structure.md`、
`docs/development/future_work.md`、`docs/development/README.md`、
`docs/development/architecture/README.md`、
`docs/development/architecture/stcache_core_category_stability.md`、
`docs/tasks/T106_semantic_type_reference_binding.md`、本合同。
documentation_result: README 保持 filelist-first，只增加 compile/elaborate 与 rename proof 的边界；能力表
纠正 value parameter/type parameter 和 physical aggregate typedef 的范围；StCache/future work/project
structure/架构索引使用同一事实；T106 只追加 post-acceptance 外部观察，不改变历史 `ACCEPTED`。
pdf_authoring: 按 PDF 技能要求，在第一次 authoring 前只执行一次 artifact marker，参数为
`--operation-kind edit --expected-output-count 2 --output-format pdf`；使用绑定 PDF 运行时和 `/private/tmp`
一次性 ReportLab 生成器同步 README.pdf 与类型表 PDF，未把生成器或依赖写入仓库。
self_tests: 公开文档目标 unittest exit 0，Ran 2、OK；状态事实与 Markdown link 检查 exit 0，
`files=125 broken=0`；PDF 门禁 exit 0，README 3 页、类型表 2 页、均为 A4 且文本可提取；README 全 3 页
渲染于 `/private/tmp/t107-pdf-render.5T3dS8/readme`，类型表最终 2 页渲染于
`/private/tmp/t107-type-final2.IcFdfi`，逐页检查无裁切、重叠、黑块、标题挤压或缺字；
`git diff --check HEAD` exit 0。
boundaries: 未修改产品代码、测试或 RTL；未运行加密、HDL、Formal、RISC-V-Vector 或 blanket discovery；
未实现 type-parameter normalization、interface 或 port macro conflict；未创建下一实现任务。
formal_verification: N/A；本任务不产生 rewritten RTL。
review_request: READY_FOR_REVIEW；请主 Agent 独立复核第 6 节五项门禁后决定是否接受。

## 9. 主 Agent 验收

status: ACCEPTED
review_head: `950be8e249450c6e4e324c9a2b7d43b8d4efb85b`
scope_review: PASS；实际修改精确为第 5 节 11 个文档/PDF 文件，未修改产品代码、测试、RTL 或 fixture。
target_tests: PASS；主 Agent 独立运行第 6.1 项，exit 0，Ran 2、OK。
documentation: PASS；主 Agent 独立运行状态事实与 Markdown link 门禁，输出
`documentation_status_and_links=pass files=125 broken=0`；T107 是验收前唯一活动任务。
pdf: PASS；README.pdf 为 3 页 A4，类型表 PDF 为 2 页 A4，文本和本轮边界关键词均可提取；主 Agent
独立渲染全部 5 页到 `/private/tmp/t107-main-review.zg7XGZ` 并逐页检查，无裁切、重叠、黑块、标题挤压
或缺字。
diff_and_guard: PASS；`git diff --check HEAD` exit 0；验收前 allowlist/status guard exit 0，输出
`t107_ready_for_review=pass allowed_files=11`。
formal_verification: N/A；T107 只更新文档和同步 PDF，不产生 rewritten RTL。
decision: ACCEPTED；当前项目目标、四组核心类别服务器状态、T106 局部验收边界和 aggregate
type-parameter 根因已同步；没有把 future work 写成已实现能力。
next_step: 暂停在文档收口状态，不创建或启动 type-parameter/interface 实现任务；等待用户明确授权下一目标。
