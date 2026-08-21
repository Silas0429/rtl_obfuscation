# T102：公开文档状态与 PDF 同步收口

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 实现负责人：GPT-5.6 Luna Extra High 子 Agent
- 前置任务：T101 已 `ACCEPTED`
- 任务类型：文档/合同
- 起始 HEAD：`9ab73b43a6f1c6e0763aa1e246ad1f27f5b40269`

## 1. 单一目标

收口当前文档审计发现的三处状态漂移：把可加密类型表中的内部实现术语改成用户可理解的边界说明；
将从未进入实现的 T006 旧草案关闭为明确的历史替代状态；从当前 `README.md` 重新生成
`README.pdf`，使显式 filelist header/context 规则保持一致。

本任务只修正文档，不改变任何加密、解密、SourceSet、SymbolGraph、mapping、rewrite、CLI 或 Formal
行为。

## 2. 固定输入与基线

- `README.md` 是 PDF 的只读内容源，不允许为适配排版而修改。
- `docs/systemverilog_renaming_table.md` 当前包含内部英文术语 `semantic owner`。
- `docs/tasks/T006_type_parameter_ranges.md` 当前仍为已暂停的 `DRAFT`，但其 `type_parameters`
  提案不属于当前公开 19 类。
- 当前 `README.pdf` 早于 README 的显式 header/context 规则更新。

子 Agent 把任务状态改成 `IN_PROGRESS` 后，必须先执行以下唯一 baseline：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_public_cli.PublicCliTests.test_readme_and_type_table_are_user_facing_and_consistent \
  tests.test_t096_public_frontend_input_modes.T096PublicFrontendInputModesTests.test_help_and_documents_are_filelist_first \
  -v
```

冻结基线：运行 2 个测试；filelist-first 测试通过；用户文档测试只因类型表包含英文内部术语
`semantic` 失败。

## 3. 必须交付

1. `docs/systemverilog_renaming_table.md` 使用面向用户的中文说明表达 T101 边界：filelist 中存在但
   当前编译配置未使用的普通 module 不参与改名，却仍原样进入 gate、manifest 和 restore；可改名
   module 与物理源码范围必须保持唯一对应。不得出现公开测试禁止的内部英文术语。
2. `docs/tasks/README.md` 新增终态 `SUPERSEDED`：仅主 Agent 可将“未实现且已被当前设计替代”的
   历史提案设为该状态；它不表示实现成功，不属于活动任务，不得恢复到 `READY`，新需求必须创建
   新任务。
3. `docs/tasks/T006_type_parameter_ranges.md` 收缩为简短历史记录并设为 `SUPERSEDED`：明确它从未进入
   `READY`、没有产生实现、`type_parameters` 不是当前公开 category，旧命令和输出合同不得继续作为
   当前开发入口。
4. `README.pdf` 必须从未经修改的当前 `README.md` 重新生成，保持 A4、3 页、文本可提取，并包含
   当前规则：显式列出的 `.svh/.vh/.h` 按顺序形成 header/context 前导，进入 gate、canonical
   `design.f`、mapping 和恢复清单；仅由 `` `include`` 发现且未显式列出的 header 不进入 canonical
   `design.f`。
5. PDF 全部页面使用 Poppler 渲染后逐页检查；不得有裁切、重叠、黑块、标题挤压或缺字方框。

## 4. PDF authoring 约束

在本任务第一次 PDF authoring 命令之前，子 Agent 必须严格执行以下 marker 一次，且整个任务不得
重复执行：

```sh
/Users/lufengchi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
  /Users/lufengchi/.codex/plugins/cache/openai-primary-runtime/pdf/26.819.11345/skills/pdf/container_tools/mark_artifact_operation_started.mjs \
  --operation-kind edit --expected-output-count 1 --output-format pdf
```

允许在 `/private/tmp` 创建一次性转换脚本、渲染图和日志；不得把生成器或新依赖写入仓库。生成器
只能读取当前 `README.md` 并写入仓库现有 `README.pdf`。

## 5. 明确不包含

- 不修改 `README.md`、测试、Python、RTL、fixture、架构或 Formal 文档；
- 不清理内部 `encrypt-vnext` / `decrypt-vnext` 兼容入口；
- 不改变 category、输入模式、filelist、header、mapping、gate 或 restore 行为；
- 不新增兼容层、fallback、生成依赖或 PDF 工具脚本；
- 不运行 HDL、加密、Formal、RISC-V-Vector 或 blanket test discovery；
- 不关闭历史 `BLOCKED` 任务 T038，也不整理其他已验收任务。

## 6. 允许修改文件

```text
README.pdf
docs/systemverilog_renaming_table.md
docs/tasks/README.md
docs/tasks/T006_type_parameter_ranges.md
docs/tasks/T102_documentation_state_and_pdf_sync.md
```

除此之外不得修改。临时文件全部放在 `/private/tmp`。

## 7. 验收命令

1. 目标文档测试：

   ```sh
   conda run -n rtl_obfuscation python -m unittest \
     tests.test_public_cli.PublicCliTests.test_readme_and_type_table_are_user_facing_and_consistent \
     tests.test_t096_public_frontend_input_modes.T096PublicFrontendInputModesTests.test_help_and_documents_are_filelist_first \
     -v
   ```

2. 任务状态与全部 Markdown 本地链接：

   ```sh
   conda run -n rtl_obfuscation python -c '
   import re
   from pathlib import Path

   files = [Path("README.md"), *sorted(Path("docs").rglob("*.md"))]
   links = [
       (source, raw, raw.strip().strip("<>").split("#", 1)[0])
       for source in files
       for raw in re.findall(r"\[[^\]]*\]\(([^)]+)\)", source.read_text(encoding="utf-8"))
   ]
   broken = [
       f"{source}:{raw}"
       for source, raw, target in links
       if target
       and "://" not in target
       and not target.startswith(("mailto:", "#"))
       and not (source.parent / target).resolve().exists()
   ]
   workflow = Path("docs/tasks/README.md").read_text(encoding="utf-8")
   legacy = Path("docs/tasks/T006_type_parameter_ranges.md").read_text(encoding="utf-8")
   assert "| `SUPERSEDED` |" in workflow
   assert "- 状态：`SUPERSEDED`" in legacy
   assert "- 状态：`DRAFT`" not in legacy
   assert not broken, broken
   print(f"documentation_state_and_links=pass files={len(files)} broken=0")
   '
   ```

3. README.pdf 文本、页数和纸张门禁：

   ```sh
   /Users/lufengchi/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 - <<'PY'
   from pypdf import PdfReader

   pdf = PdfReader("README.pdf")
   text = "".join("".join((page.extract_text() or "").split()) for page in pdf.pages)
   assert len(pdf.pages) == 3
   assert all(float(page.mediabox.width) > 590 and float(page.mediabox.height) > 840 for page in pdf.pages)
   assert "显式列出的.svh/.vh/.h按首次出现顺序组成header/context前导" in text
   assert "进入gate、canonicaldesign.f、mapping和恢复清单" in text
   assert "发现的未列出header只进入物理清单，不进入canonicaldesign.f" in text
   print("README.pdf pages=3 explicit_header_rule_and_a4=pass")
   PY
   ```

   第 3 项通过后，还必须执行 `pdftoppm -png -r 120 README.pdf <临时目录>/page` 并逐页检查；
   渲染和人工检查属于同一 PDF 验收项，不新增第六条命令。

4. diff 检查：

   ```sh
   git diff --check HEAD
   ```

5. 精确状态与允许文件 guard：

   ```sh
   conda run -n rtl_obfuscation python -c '
   import subprocess
   from pathlib import Path

   allowed = {
       "README.pdf",
       "docs/systemverilog_renaming_table.md",
       "docs/tasks/README.md",
       "docs/tasks/T006_type_parameter_ranges.md",
       "docs/tasks/T102_documentation_state_and_pdf_sync.md",
   }
   status = subprocess.run(
       ["git", "status", "--porcelain"], check=True, text=True, capture_output=True
   ).stdout.splitlines()
   changed = {line[3:] for line in status if line}
   task = Path("docs/tasks/T102_documentation_state_and_pdf_sync.md").read_text(encoding="utf-8")
   status_line = next(line for line in task.splitlines() if line.startswith("- 状态："))
   assert changed == allowed, (changed, allowed)
   assert status_line == "- 状态：`READY_FOR_REVIEW`", status_line
   print("ready_for_review_guard=pass allowed_files=5")
   '
   ```

## 8. Formal verification

```text
formal_verification: N/A
reason: T102 only updates documentation and README.pdf; it produces no rewritten RTL
```

## 9. 子 Agent 执行记录

status: READY_FOR_REVIEW
starting_head: 9ab73b43a6f1c6e0763aa1e246ad1f27f5b40269
start_time: 2026-08-21 Asia/Shanghai；已确认 READY，工作区仅有本合同未跟踪
review_correction: 主 Agent 第一轮审阅拒绝；仅补全 `docs/tasks/README.md` 中 `SUPERSEDED` 的终态、不得恢复 `READY`、新需求新建任务语义；不修改其他内容，不重生成 README.pdf，不重复 marker
correction_commands: 重新执行合同第 7 节目标测试、文档状态与链接检查、现有 README.pdf 文本/A4 门禁、Poppler 全页渲染与视觉检查、`git diff --check HEAD` 和 READY_FOR_REVIEW 允许文件 guard
correction_results: 目标测试 exit 0，Ran 2，OK；文档状态与全部 Markdown 本地链接检查 exit 0；现有 README.pdf 未重生成，marker 未重复，文本/A4 门禁 exit 0，3 页规则通过；重新渲染到 `/private/tmp/t102-pdf-review-correction.Fr1ekl`，3 页逐页检查无裁切、重叠、黑块或缺字；`git diff --check HEAD` exit 0；READY_FOR_REVIEW guard exit 0，allowed_files=5
review_correction_2: 主 Agent 第二轮验收拒绝；合同原第 2、5 条使用 `conda run ... python -` heredoc，探针证明 stdin 未转交且脚本未执行仍 exit 0；主 Agent 仅将两条门禁修正为真正执行的 `python -c`，任务回到 IN_PROGRESS；不改变交付目标、允许文件或验收项
review_correction_3: 第二轮修正后的第 5 项真实执行时发现全文禁止 `- 状态：ACCEPTED` 会匹配合同命令自身；主 Agent 仅将 guard 收紧为解析文档顶部唯一 `- 状态：` 行并要求精确等于 `READY_FOR_REVIEW`；任务保持 IN_PROGRESS
correction_3_commands: 完整核对修正后的第 7 节；重新执行目标测试、multiline `python -c` 文档状态与链接检查、现有 README.pdf 文本/A4 门禁、Poppler 全 3 页渲染与视觉检查、`git diff --check HEAD`；更新本记录与顶部状态后执行解析首个状态行的 multiline `python -c` READY_FOR_REVIEW guard
correction_3_results: 目标测试 exit 0，Ran 2，OK；第 2 项 exit 0 并明确输出 `documentation_state_and_links=pass files=119 broken=0`；现有 README.pdf 未重生成且 marker 未重复，第 3 项 exit 0 并输出 `README.pdf pages=3 explicit_header_rule_and_a4=pass`；重新渲染到 `/private/tmp/t102-pdf-review-correction3.b1J6j0`，3 页逐页检查无裁切、重叠、黑块、标题挤压或缺字；`git diff --check HEAD` exit 0；修正后的第 5 项 exit 0 并明确输出 `ready_for_review_guard=pass allowed_files=5`
correction_2_commands: 完整核对修正后的第 7 节，并重新执行目标测试、multiline `python -c` 文档状态与链接检查、现有 README.pdf 文本/A4 门禁、Poppler 全 3 页渲染与视觉检查、`git diff --check HEAD`、multiline `python -c` READY_FOR_REVIEW guard，以及只读断言定位探针
correction_2_results: 目标测试 exit 0，Ran 2，OK；第 2 项 exit 0 并明确输出 `documentation_state_and_links=pass files=119 broken=0`；现有 README.pdf 未重生成且 marker 未重复，第 3 项 exit 0 并输出 `README.pdf pages=3 explicit_header_rule_and_a4=pass`；重新渲染到 `/private/tmp/t102-pdf-review-correction2.zuVx8g`，3 页逐页检查无裁切、重叠、黑块、标题挤压或缺字；`git diff --check HEAD` exit 0；第 5 项真实执行但 exit 1，允许文件集合断言通过，失败原因是合同第 180 行自身包含精确文本 `- 状态：ACCEPTED`，与“整份任务不得包含该文本”的断言自冲突；只读探针输出 `allowed_match=True`、`ready_status_present=True`、`accepted_status_literal_occurrences=1`、`accepted_literal_lines=180`
first_command: 按第 7 节运行目标文档测试 baseline
allowed_files: README.pdf；docs/systemverilog_renaming_table.md；docs/tasks/README.md；docs/tasks/T006_type_parameter_ranges.md；docs/tasks/T102_documentation_state_and_pdf_sync.md
changed_files: README.pdf；docs/systemverilog_renaming_table.md；docs/tasks/README.md；docs/tasks/T006_type_parameter_ranges.md；docs/tasks/T102_documentation_state_and_pdf_sync.md
commands: baseline 目标测试；合同第 7 节命令 1–5；PDF marker；`/Users/lufengchi/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 /private/tmp/t102_readme_to_pdf.py README.md`；`pdftoppm -png -r 120 README.pdf /private/tmp/t102-pdf-render.ZziGkQ/page`
results: baseline exit 1，Ran 2，filelist-first 通过，文档测试仅因 `semantic` 失败；目标测试 exit 0，Ran 2，OK；文档状态与链接检查 exit 0，全部 Markdown 本地链接通过；README.pdf marker exit 0 且全任务仅执行一次，生成 exit 0；PDF 文本/A4 门禁 exit 0，3 页且显式 header/context 规则通过；Poppler 渲染 exit 0，生成 page-1.png、page-2.png、page-3.png，逐页检查通过；`git diff --check HEAD` exit 0；README.md 未修改
schema_or_behavior: 文档状态与 PDF 同步；T101 边界改为用户可理解的中文说明；新增 SUPERSEDED 终态并关闭 T006 历史草案；不改变产品行为
boundaries: 不修改 README.md、代码、测试、RTL、其他文档或 PDF 生成器；不运行 HDL、加密、Formal、RISC-V-Vector 或 blanket discovery；内部 encrypt-vnext/decrypt-vnext 兼容入口和 T038 BLOCKED 保持原状
cleanup_candidates: 内部 encrypt-vnext/decrypt-vnext 兼容入口不属于本任务
formal_verification: N/A；本任务不产生 rewritten RTL
review_request: READY_FOR_REVIEW；第三轮修正后的五项门禁全部真实执行并通过，请主 Agent 独立复跑第 7 节并检查 `/private/tmp/t102-pdf-review-correction3.b1J6j0` 对应的 3 页 PDF 后决定 ACCEPTED；子 Agent 未 commit、push 或设置 ACCEPTED

## 10. 主 Agent 验收

status: ACCEPTED
review_head: `9ab73b43a6f1c6e0763aa1e246ad1f27f5b40269`
implementation_review: PASS；实际差异仅为 5 个允许文件；类型表改成用户可理解的边界，T006 收缩为
  `SUPERSEDED` 历史记录，工作流明确该状态为不可恢复终态；`README.md`、产品代码和测试均未修改
target_tests: PASS；主 Agent 独立运行第 7.1 项，exit 0，Ran 2，OK
documentation: PASS；主 Agent 独立运行修正后的第 7.2 项，明确输出
  `documentation_state_and_links=pass files=119 broken=0`
pdf: PASS；主 Agent独立运行第 7.3 项，明确输出
  `README.pdf pages=3 explicit_header_rule_and_a4=pass`；独立渲染全部页面到
  `/tmp/t102-main-pdf.Onlw7p` 并逐页检查，A4 三页无裁切、重叠、黑块、标题挤压或缺字
diff_and_guard: PASS；`git diff --check HEAD` exit 0；修正后的 READY_FOR_REVIEW guard 在接受前
  exit 0，并明确输出 `ready_for_review_guard=pass allowed_files=5`
formal_verification: N/A；T102 只更新文档和 PDF，不产生 rewritten RTL
decision: ACCEPTED；公开文档状态、用户术语和 README.pdf 已同步，未改变产品行为
next_step: 不新建实现任务；下一步仅使用已交付版本在服务器重跑 StCache 显式 filelist signals 测试
delivery: 等待本次接受记录纳入文档提交并推送
