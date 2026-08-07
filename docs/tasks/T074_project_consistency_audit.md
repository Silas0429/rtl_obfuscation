# T074：项目设计一致性复核与文档状态整理

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 设计日期：2026-07-31
- 前置任务：T073 `ACCEPTED`，交付提交 `4af1772905497d1524f7c33c9ef38eb34f966574`
- 任务类型：文档一致性与交付物质量整理
- Formal verification：`N/A`，本任务不修改实现、不生成 rewritten RTL

## 1. 单一目标

在不改变任何加密行为的前提下，把当前实现、权威设计和项目状态重新对齐：

1. 修复文档重组后遗留的 20 个失效本地 Markdown 链接；
2. 将 T069–T073 后真实工程复测确认的新边界写入 `future_work.md`，明确区分
   “错误加密风险”与“少加密/拒绝加密”；
3. 使用主 Agent 冻结的一次性 `/tmp` 生成器，从未修改的 `README.md` 重生成
   `README.pdf`，消除 inline code 中中文文字的缺字方框；
4. 保持产品实现、公开入口、schema、CLI、测试、RTL、wheel 和现有任务状态不变。

本任务不实现任何新语法支持，不修复真实工程边界，不创建 T075。

## 2. 起始状态

```text
starting_head: 4af1772905497d1524f7c33c9ef38eb34f966574
branch: main
local_head_equals_origin_main: true
worktree: clean
active_tasks: none
historical_draft: T006
historical_blocked: T038 BLOCKED / NOT_ACCEPTED
T069..T073: ACCEPTED
```

主 Agent 审计证据：

```text
explicit_non_risc_regression: 233/233 PASS
py_compile: PASS
README project-root smoke: PASS
strict_compile: PASS
restore: 4 files byte-identical
actual_gate_formal: PASS, top=fifo_top, seq=5
wheel_archive_and_metadata: PASS, pyslang=11.0.0, cp311, manylinux2014/manylinux_2_17
broken_local_markdown_links: 20
README.pdf: 6 pages; page 5 has missing-glyph boxes in inline Chinese code text
```

## 3. 冻结输入

### 3.1 README 与一次性 PDF 生成器

```text
README.md sha256:
f7ccfc7b0976fc3f126b6418e2c0d0363759143102d53f3b04bb76e2f5adf956

/tmp/rtl_markdown_to_pdf.py sha256:
8a2991b2f4be07b8510c19b603ab4a48f196c837e3b5d7e5118860c621c2dc65
```

`README.md` 和 `/tmp/rtl_markdown_to_pdf.py` 均为只读输入。生成命令固定为：

```sh
/Users/lufengchi/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  /tmp/rtl_markdown_to_pdf.py README.md
```

不得把一次性生成器复制进仓库，不得修改 README 文字来规避 PDF 字体问题。

### 3.2 允许整理的现有文件哈希

```text
3f752ca6721db216f64b66532a7421ac5798345c92c0d43e76c3eecee2a9e200  docs/tasks/T027_project_root_top_analysis.md
2f6c26dd5d90731da67e0f8ff22cf8d9e00e702a3d46feba6b93cf8e8154aac9  docs/tasks/T028_project_root_rewrite.md
2af4977b1321b77fec9726a6ad007c8dd58df546b447889c1eb48435f803cf7c  docs/tasks/T029_risc_v_vector_delivery.md
b6e93ea480fa76b91c39da946f2330dfa0f28100bd689aa286e4260600703e68  docs/tasks/T031_project_root_parameters.md
7d445f696ea34028475ab490e7fbfd17676a6b0d18029551c3ce983dd12bc11f  docs/tasks/T032_project_root_parameter_rewrite.md
d90928fd5dd1328b948e39038c2b7170e331e83d9f13690409086dddb768153e  docs/tasks/T033_impact_category_oracle.md
3a17732a7b523147135549eb64a33e83936e55eea83483bc9c0acfd82b542599  docs/tasks/T034_single_file_default_profile.md
c3be4c0dfe34d62a9188e28fb2ba2054e2355edb3794e3c878b0fc22a58eb610  docs/development/architecture/project_root_top_roadmap.md
dda8304d6a037d3383df79fc8474a6586c7ed3a3d0a725416b6080239aeb9dd6  docs/development/architecture/three_mode_refactor_plan.md
a72712908b99b4a1fda25bb26438ebec2c98767156e309ba87f2e8a299439571  docs/development/future_work.md
9c60267e778c9315de9f691b8ff3d0c275178236c87cca9edde5670d3c7dd4c5  README.pdf
```

任一冻结输入在子 Agent 开始前不匹配时必须停止，不得猜测合并。

## 4. 精确链接整理范围

只修正链接目标，不改写历史任务合同正文或历史证据：

- T027、T028、T029：
  `../project_root_top_roadmap.md` →
  `../development/architecture/project_root_top_roadmap.md`；
- T031、T032：
  `../project_root_parameter_plan_draft.md` →
  `../development/architecture/project_root_parameter_plan_draft.md`；
- T033、T034：
  `../category_profile_normalization_plan.md` →
  `../development/architecture/category_profile_normalization_plan.md`；
- `project_root_top_roadmap.md`：
  `systemverilog_renaming_table.md` →
  `../../systemverilog_renaming_table.md`；
- `three_mode_refactor_plan.md` 中 T040–T051 的 `tasks/...` →
  `../../tasks/...`。

整理后根 README 与 `docs/**/*.md` 的本地 Markdown 链接必须全部存在。

## 5. `future_work.md` 边界整理

只新增一个“T073 后真实工程复测边界”小节，必须准确记录：

- quarantined owner 内跨 owner occurrence 仍可能形成半改名；当前 register_interface
  被 strict compile 拦截，但正确性优先级最高的后续项是 owner occurrence firewall；
- direct identifier sized-cast 已支持，但 enum/base dimension 与 expression-sized cast
  仍可能漏收集；
- module end label 尚未纳入 module rename occurrence；
- package-qualified enum/member 的右侧物理范围仍可能无法和 semantic target 对齐；
- 同一 module owner 同时命中 type-parameter、nested-generate 或 macro quarantine 时，
  conflicting reasons 仍原子失败；
- syntax-less implicit typedef conversion 没有可证明的直接源码 token 时继续 fail-closed；
- VeeR 宏 module definition name、SCR1 header/package 宏位置、Ibex 缺外部 primitive
  分别属于 owner/build-input 边界。

必须明确写出：

- 上述案例没有错误 gate 被发布；
- “安全拒绝或少加密”不是“支持成功”；
- 不得以 strict compile 代替可运行时的 actual-gate Formal；
- 本任务只记录，不授权实现。

不得改动 T069–T073 已有支持说明的语义。

## 6. README.pdf 整理

- `README.md` 必须保持 byte-identical；
- 重生成后仍为 A4、6 页、文本可提取；
- 必须包含 `python -m venv .venv`、默认 13 类、全部 19 类、加密和解密命令；
- 六页全部渲染检查，不得有缺字方框、截断、重叠或黑块；
- 特别检查第 5 页 ``--report <恢复报告.json>``；
- 不修改另外两份 PDF。

## 7. 允许修改

```text
README.pdf
docs/development/future_work.md
docs/development/architecture/project_root_top_roadmap.md
docs/development/architecture/three_mode_refactor_plan.md
docs/tasks/T027_project_root_top_analysis.md
docs/tasks/T028_project_root_rewrite.md
docs/tasks/T029_risc_v_vector_delivery.md
docs/tasks/T031_project_root_parameters.md
docs/tasks/T032_project_root_parameter_rewrite.md
docs/tasks/T033_impact_category_oracle.md
docs/tasks/T034_single_file_default_profile.md
docs/tasks/T074_project_consistency_audit.md
```

除此之外不得修改。特别禁止修改：

- `rtl_obfuscator/**`、`rtl_encrypt.py`、`rtl_decrypt.py`；
- `tests/**`、`rtl_samples/**`、`wheel/**`；
- `README.md`、category table、Formal 文档和 T069–T073 合同；
- `/tmp/rtl_markdown_to_pdf.py`。

## 8. 唯一验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_public_cli.PublicCliTests.test_readme_and_type_table_are_user_facing_and_consistent -v

conda run -n rtl_obfuscation python -c \
  'import pathlib,re; files=[pathlib.Path("README.md"),*pathlib.Path("docs").rglob("*.md")]; bad=[]; [(bad.append((str(f),t)) if (p:=t.split("#",1)[0]) and "://" not in p and not (f.parent/p).resolve().exists() else None) for f in files for t in re.findall(r"\[[^\]]+\]\(([^)]+)\)",f.read_text(encoding="utf-8"))]; assert not bad,bad; text=pathlib.Path("docs/development/future_work.md").read_text(encoding="utf-8"); required=("owner occurrence firewall","expression-sized cast","module end label","package-qualified enum/member","conflicting quarantine reasons","syntax-less implicit typedef conversion","没有错误 gate 被发布"); assert all(item in text for item in required)'

/Users/lufengchi/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -c 'from pypdf import PdfReader; p=PdfReader("README.pdf"); t="\n".join(page.extract_text() or "" for page in p.pages); assert len(p.pages)==6; assert all(x in t for x in ("python -m venv .venv","默认加密 13 类","全部 19 类","python rtl_encrypt.py","python rtl_decrypt.py","恢复报告.json")); print("README.pdf pages=6 text_check=pass")'

git diff --check HEAD

rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T074_project_consistency_audit.md
```

第三条命令通过后还必须把 README.pdf 六页渲染为 PNG 并逐页人工检查；渲染属于同一 PDF
验收步骤，不新增产品测试命令。

## 9. 子 Agent 行为规范

1. 完整阅读 `AGENTS.md`、本合同、`docs/tasks/README.md` 和 PDF 生成要求；
2. 校验起始 HEAD、工作树、冻结哈希和唯一活动任务；
3. 第一次编辑前将状态改为 `IN_PROGRESS`，记录启动信息；
4. 只修改第 7 节文件；
5. 不运行 blanket discovery、RISC-V-Vector Formal 或历史 acceptance driver；
6. 不修改任何实现、测试、RTL、README Markdown、wheel 或另外两份 PDF；
7. 完成后记录 changed files、20→0 链接结果、future-work 边界、PDF 文本/六页视觉结果；
8. 运行第 8 节五条命令，将状态设置为 `READY_FOR_REVIEW` 后停止；
9. 不 stage、commit、push，不设置 `ACCEPTED`，不创建 T075。

## 10. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 4af1772905497d1524f7c33c9ef38eb34f966574; origin/main matches
hash_check: PASS; README.md, /tmp generator, and all 11 frozen repository inputs match exactly
changed_files: README.pdf; docs/development/future_work.md;
  docs/development/architecture/project_root_top_roadmap.md;
  docs/development/architecture/three_mode_refactor_plan.md;
  docs/tasks/T027_project_root_top_analysis.md;
  docs/tasks/T028_project_root_rewrite.md;
  docs/tasks/T029_risc_v_vector_delivery.md;
  docs/tasks/T031_project_root_parameters.md;
  docs/tasks/T032_project_root_parameter_rewrite.md;
  docs/tasks/T033_impact_category_oracle.md;
  docs/tasks/T034_single_file_default_profile.md;
  docs/tasks/T074_project_consistency_audit.md
link_audit: PASS; exactly 20 frozen broken targets corrected; all README/docs local Markdown
  targets now exist (20 -> 0)
future_work: PASS; added only "T073 后真实工程复测边界"; records the owner-occurrence
  half-rename risk, remaining sized-cast/module-label/package-range/quarantine/conversion
  boundaries, and VeeR/SCR1/Ibex owner/build-input boundaries; explicitly distinguishes
  wrong-gate risk from safe refusal or reduced encryption and does not authorize implementation
pdf: PASS; frozen generator exit 0; README.md remains byte-identical at
  f7ccfc7b0976fc3f126b6418e2c0d0363759143102d53f3b04bb76e2f5adf956;
  README.pdf is A4, 6 pages, text-extractable, and contains all frozen required strings;
  all 6 rendered PNG pages inspected with no missing glyph boxes, clipping, overlap, or
  black blocks; page 5 "--report <恢复报告.json>" renders completely; no other PDF modified
commands: section 8 commands 1-5 executed exactly as frozen; README.pdf generation used the
  exact section 3.1 command; six-page rendering used pdftoppm as the same PDF acceptance step
results: command 1 exit 0, 1/1 OK; command 2 exit 0, no broken links and all required
  boundary phrases present; command 3 exit 0,
  "README.pdf pages=6 text_check=pass"; command 4 exit 0, no output; command 5 exit 0,
  exact READY_FOR_REVIEW status line matched
formal_verification: N/A
reason: documentation-only task; no rewritten RTL is produced
review_request: READY; main Agent should independently rerun section 8 and inspect all six
  rendered PDF pages before ACCEPTED
```

## 11. 主 Agent 验收

```text
status: ACCEPTED
accepted_date: 2026-07-31
accepted_head_before_commit: 4af1772905497d1524f7c33c9ef38eb34f966574
allowed_files: PASS; only section 7 repository files changed
implementation_changes: none
README_md_sha256:
  f7ccfc7b0976fc3f126b6418e2c0d0363759143102d53f3b04bb76e2f5adf956
link_audit: PASS; 20 -> 0 broken local Markdown links
future_work: PASS; post-T073 boundaries and safety priority are accurate and non-authorizing
README_pdf:
  PASS; A4; 6 pages; text extraction passed; all six pages independently rendered and
  inspected; no missing glyph boxes, clipping, overlap, or black blocks; page 5
  "--report <恢复报告.json>" is complete
acceptance:
  command 1 exit 0; 1/1 unittest OK
  command 2 exit 0; links and required boundary phrases PASS
  command 3 exit 0; README.pdf pages=6 text_check=pass
  command 4 exit 0; git diff --check HEAD produced no output
  command 5 exit 0; READY_FOR_REVIEW guard matched before acceptance
formal_verification: N/A
reason: documentation-only task; no rewritten RTL is produced
decision: all frozen T074 requirements passed; ACCEPTED
successor: no T075 created
```
