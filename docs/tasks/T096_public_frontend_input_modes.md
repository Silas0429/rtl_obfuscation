# T096：filelist-first 公共加密前端与严格三模式参数矩阵

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：GPT-5.6 Luna Extra high 子 Agent
- 前置任务：T087–T095，当前实现基线 `ee702c3`
- 任务类型：adapter migration + public documentation + compact end-to-end/Formal
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：必须使用一个实际改名 filelist gate 完成正例和固定功能负例

## 1. 单一目标

收紧公共 `rtl_encrypt.py` 的三种输入模式，并将用户入口调整为 filelist-first：

```text
single-file：--input FILE
filelist：   --filelist DESIGN.F [--top TOP]
project-root：--source-root DIR --top TOP
```

公共单文件不再要求或接受 `--source-root`，输入文件参数本身就是路径；filelist 继续禁止
`--source-root`；只有 project-root 同时使用 `--source-root` 和 `--top`。任何模式选择参数混用都必须
在创建 output、mapping 或 metrics 前给出具体诊断。三种入口仍只建立同一种 `SourceSet`，后续
SymbolGraph、RewritePolicy、MappingVNext、gate、restore、metrics 和 Formal 流水线不得分叉。

用户手册以真实工程的 filelist 路径为主流程；single-file 和 project-root 只保留简短辅助说明。

## 2. 冻结输入合同

### 2.1 公共 CLI 参数矩阵

| 模式 | 必须参数 | 模式专属可选参数 | 明确禁止 |
| --- | --- | --- | --- |
| single-file | `--input FILE` | 无 | `--source-root`、`--filelist`、`--top` |
| filelist | `--filelist DESIGN.F` | `--top TOP` | `--input`、`--source-root` |
| project-root | `--source-root DIR --top TOP` | 无 | `--input`、`--filelist` |

以下公共选项不是模式选择器，可在三种模式中继续使用：`--include-dir`、`--define`、`--category`、
`--encryption-rate`、`--name-length`、`--output-dir`、`--map`、`--metrics`。

- single-file 的 `--input` 相对路径按当前工作目录解析；内部 source root 固定为解析后输入文件的父目录。
- single-file 的相对 `--include-dir` 按输入文件父目录解析，并继续受现有越根保护；需要跨目录、多源文件或
  自定义编译顺序时应使用 filelist。
- single-file 不接受 `--top`，继续只使用当前默认 13 个非 ABI 类别；手动 `--category` 只选择用户给出的类别。
- filelist 的 root 自动推导、环境变量、嵌套 `-f`、`+incdir+`、`+define+`、`.sv/.v/.svh/.vh/.h`
  和 bounded candidate universe 保持不变；自动 root 不得扫描未列源码。
- filelist 不提供 top 时使用默认 13 类；提供 top 时可使用当前 19 类并保持 top 名称和对外端口。
- project-root 只有 `--source-root` 和 `--top` 同时存在才成立；缺任意一个都失败，不得降级为 single-file
  或 filelist。
- 内部 `python -m rtl_obfuscator.rewrite encrypt-vnext` 的历史 `--input/--filelist/--project-root`
  参数合同保持不变；本任务只收紧公共 `rtl_encrypt.py`。

### 2.2 输入错误输出

所有模式冲突首行保持：

```text
error: CLI_VNEXT_INPUT_INVALID
```

并必须至少给出 `detail`、`message` 和统一 `hint`：

```text
detail: CLI_VNEXT_INPUT_MODE_CONFLICT | CLI_VNEXT_INPUT_MODE_INCOMPLETE
message: <指出当前模式、非法参数和合法形式>
hint: 单文件只用 --input；推荐的 filelist 使用 --filelist [--top]；project-root 使用 --source-root + --top。
```

至少固定以下失败：

1. `--input + --source-root`；
2. `--input + --top`；
3. `--input + --filelist`；
4. `--filelist + --source-root`；
5. `--filelist + --input`；
6. `--filelist + --source-root + --top`；
7. 只有 `--source-root`；
8. 只有 `--top`；
9. `--source-root + --top + --filelist`；
10. 三种选择器同时出现。

参数冲突必须先于路径存在性、SourceSet discovery、输出目录创建和报告写入检查；失败不得有 traceback。

## 3. 用户文档合同

- `README.md` 的首个工程命令和快速成功路径改为显式 filelist；先解释 filelist、top 可选、编译上下文和
  `rename/preserve/unsupported`，再用一个短小的“其他输入模式”段落说明 single-file/project-root。
- README 不再把 single-file 作为默认快速开始，也不再展示 single-file 的 `--source-root`。
- `docs/formal_verification.md` 的多文件命令不得再包含 `--filelist + --source-root`；single-file 命令只使用
  `--input FILE`。
- `docs/development/project_structure.md` 同步公共三模式参数矩阵，但保持内部 API/SourceSet 架构说明。
- `README.pdf` 必须由更新后的 README 同步生成；在第一次 PDF authoring 前，子 Agent 必须严格执行一次：

  ```sh
  /Users/lufengchi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
    /Users/lufengchi/.codex/plugins/cache/openai-primary-runtime/pdf/26.818.11542/skills/pdf/container_tools/mark_artifact_operation_started.mjs \
    --operation-kind edit --expected-output-count 1 --output-format pdf
  ```

  PDF 必须为 A4、文本可提取；全部页面使用 Poppler 渲染并检查无裁切、重叠、黑块和缺字。

## 4. Compact 黑盒验收

新增 `tests/test_t096_public_frontend_input_modes.py`，复用现有 `rtl_samples/example_fifo/` 与 compact
fixtures，不修改 RTL fixture。测试必须覆盖：

1. 公共 single-file 只用绝对或相对 `--input` 成功，source-set origin 为 `single-file`，不传 top；
2. 公共 filelist 无 top 和有 top 均成功，始终不传 `--source-root`；
3. 公共 project-root 只用 `--source-root + --top` 成功；
4. 2.2 的全部非法组合都返回稳定 detail/message/hint，stdout 为空且没有任何输出；
5. `--help` 和三份文档只展示冻结的三种形式，并以 filelist 为推荐主流程；
6. 一个 `--category signals` 的 FIFO filelist actual gate：`rename > 0`、strict compile true、direct restore
   四个文件 byte-identical；
7. 同一 actual gate 的 Formal 正例退出 0 且 JSON `formal_equivalence=pass`；固定把一个 RHS 运算符改变后，
   gate 仍严格编译但 Formal 必须非零并包含 `unproven` 与 `equiv_status -assert`；
8. 同步本合同允许文件内因 T093/T086 已改变的详细错误和 summary 文本旧断言，使目标回归全部通过；
   不得删除测试或放宽产品行为。

## 5. 明确不包含

- 不改变19个 category、ABI/top-boundary、SymbolGraph、MappingVNext、rate、metrics 或 restore schema；
- 不改变 internal `encrypt-vnext` 的合法参数合同；
- 不把 filelist 自动 root 变成 project-root 扫描，不为缺失 module/interface 猜测 provider；
- 不新增 vendor filelist、shell、glob、library map、blackbox、宏加密或第二套 parser；
- 不修改 RTL fixture，不删除历史测试，不运行 RISC-V-Vector Formal；
- 不顺带处理服务器 `CsrLocalBusIf` 缺失输入；该问题仍属于真实 build-input 闭包；
- 如需修改允许文件外内容或改变上述行为，子 Agent 必须记录偏差并停止，不得扩大任务。

## 6. 允许修改

```text
README.md
README.pdf
docs/formal_verification.md
docs/development/project_structure.md
docs/tasks/T096_public_frontend_input_modes.md
rtl_obfuscator/rewrite.py
tests/test_t096_public_frontend_input_modes.py
tests/test_public_cli.py
tests/test_cli_vnext_encryption.py
tests/test_restore_vnext.py
tests/test_t088_verilog_suffix.py
tests/test_t091_h_macro_header.py
tests/test_t093_macro_fallback_and_cli_validation.py
tests/test_vnext_product_surface.py
```

下列主Agent在 T096 建立前完成的状态同步是已知 pre-existing change，子 Agent 不得修改：

```text
docs/tasks/T092_filelist_input_mode.md
docs/tasks/T093_macro_fallback_and_cli_validation.md
docs/tasks/T094_builtin_preprocessor_macros.md
docs/tasks/T095_macro_formal_parameters.md
```

子 Agent 不得 commit、push 或设置 `ACCEPTED`。

## 7. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t096_public_frontend_input_modes tests.test_public_cli \
  tests.test_cli_vnext_encryption tests.test_restore_vnext \
  tests.test_t088_verilog_suffix tests.test_t091_h_macro_header \
  tests.test_t092_filelist_input_mode tests.test_t093_macro_fallback_and_cli_validation \
  tests.test_vnext_product_surface -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rewrite.py tests/test_t096_public_frontend_input_modes.py \
  tests/test_public_cli.py tests/test_cli_vnext_encryption.py tests/test_restore_vnext.py \
  tests/test_t088_verilog_suffix.py tests/test_t091_h_macro_header.py \
  tests/test_t093_macro_fallback_and_cli_validation.py tests/test_vnext_product_surface.py

/Users/lufengchi/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -c \
  'from pathlib import Path; from pypdf import PdfReader; readme=Path("README.md").read_text(encoding="utf-8"); formal=Path("docs/formal_verification.md").read_text(encoding="utf-8"); pdf=PdfReader("README.pdf"); text="\n".join(page.extract_text() or "" for page in pdf.pages); assert "--filelist" in readme; assert "单文件：--input FILE --source-root DIR" not in readme; assert "--source-root <原始项目>" not in formal; assert "--source-root <原始目录>" not in formal; assert all(x in text for x in ("filelist", "--input", "project-root")); assert all(float(p.mediabox.width) > 590 and float(p.mediabox.height) > 840 for p in pdf.pages); print(f"README.pdf pages={len(pdf.pages)} filelist_first_and_a4=pass")'

git diff --check HEAD

conda run -n rtl_obfuscation python -c \
  'from pathlib import Path; text=Path("docs/tasks/T096_public_frontend_input_modes.md").read_text(encoding="utf-8"); assert "- 状态：`READY_FOR_REVIEW`" in text; print("READY_FOR_REVIEW guard=pass")'
```

第三项通过后，还必须将全部 README.pdf 页面渲染为 PNG；子 Agent 记录路径和检查结果，主 Agent 独立
重新渲染并逐页查看。第一项中的 T096 测试负责记录 compact actual-gate Formal 正负例的 gold、gate、top、
完整命令、退出码和关键输出。禁止 blanket discovery 和 RISC-V-Vector Formal。

## 8. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: ee702c3bbd8f4177475f5a0d13dcbfd0579c0ee8
start_time: 2026-08-19T14:54:14+08:00
start_command: `git status --short --branch`
review_correction: 主 Agent 第一轮验收拒绝；按原 T096 计划补充功能负例的严格语义编译零错误断言，修正合同 PDF 验收解释器路径为绑定 PDF 技能运行时；不重新运行 artifact marker，不重生成 README.pdf，不扩大范围
review_correction_2: 主 Agent 第二轮验收拒绝；删除第 7 节第 3 条中多余的 `conda run -n rtl_obfuscation python -c`，使 PDF guard 直接使用绑定 PDF 技能运行时；不修改实现或 README.pdf，不重新运行 artifact marker
allowed_files: README.md, README.pdf, docs/formal_verification.md, docs/development/project_structure.md, docs/tasks/T096_public_frontend_input_modes.md, rtl_obfuscator/rewrite.py, tests/test_t096_public_frontend_input_modes.py, tests/test_public_cli.py, tests/test_cli_vnext_encryption.py, tests/test_restore_vnext.py, tests/test_t088_verilog_suffix.py, tests/test_t091_h_macro_header.py, tests/test_t093_macro_fallback_and_cli_validation.py, tests/test_vnext_product_surface.py
preexisting_changes: Main Agent status synchronization in T092–T095; T096 contract; T092–T095 are not modified by this task
changed_files: README.md; README.pdf; docs/formal_verification.md; docs/development/project_structure.md; docs/tasks/T096_public_frontend_input_modes.md; rtl_obfuscator/rewrite.py; tests/test_t096_public_frontend_input_modes.py; tests/test_public_cli.py; tests/test_cli_vnext_encryption.py; tests/test_restore_vnext.py; tests/test_t088_verilog_suffix.py
artifact_marker: exact command `/Users/lufengchi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node /Users/lufengchi/.codex/plugins/cache/openai-primary-runtime/pdf/26.818.11542/skills/pdf/container_tools/mark_artifact_operation_started.mjs --operation-kind edit --expected-output-count 1 --output-format pdf`; exit 0; executed exactly once before the original PDF authoring; review correction did not rerun it
commands: fixed section 7 command 1 unittest; fixed section 7 command 2 py_compile; fixed section 7 command 3 corrected direct bound-runtime PDF text/A4 guard; existing `pdftoppm -png -r 120 README.pdf /private/tmp/t096-pdf-render-final/page` render; fixed section 7 command 4 `git diff --check HEAD`; fixed section 7 command 5 READY_FOR_REVIEW guard
results: baseline first run had 53 tests and the T096 module was absent; first review correction reran all five fixed commands: unittest exit 0, Ran 56 tests in 16.937s, OK; py_compile exit 0; PDF guard exit 0 with `README.pdf pages=3 filelist_first_and_a4=pass`; existing final PDF render remains `/private/tmp/t096-pdf-render-final` and all 3 pages were visually checked; diff check exit 0; status guard exit 0. Second review correction ran the corrected section 7 command 3 with exit 0 and `README.pdf pages=3 filelist_first_and_a4=pass`, `git diff --check HEAD` exit 0, and READY_FOR_REVIEW guard exit 0.
schema_or_behavior: Public single-file accepts only `--input` and derives its parent as the internal root; public filelist accepts only `--filelist` with optional `--top` and auto-infers its root; public project-root requires exactly `--source-root` plus `--top`; all public mode conflicts fail before output publication with detail/message/hint; internal encrypt-vnext contract unchanged; documentation is filelist-first
boundaries: frozen by sections 2 and 5
cleanup_candidates: none; stale assertions must be synchronized, not deleted
formal_verification: PASS; gold: `rtl_samples/example_fifo/design.f` with root `rtl_samples/example_fifo`; gate: `/private/tmp/t096-readme-quick/gate/design.f` with root `/private/tmp/t096-readme-quick/gate`; top: `fifo_top`; positive command: `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist rtl_samples/example_fifo/design.f --gold-root rtl_samples/example_fifo --gate-filelist /private/tmp/t096-readme-quick/gate/design.f --gate-root /private/tmp/t096-readme-quick/gate --top fifo_top --seq 5`; positive exit 0, JSON `formal_equivalence=pass`; fixed functional negative gate: `/private/tmp/t096-formal-negative.Z15P07` after one RHS `== DEPTH` to `!= DEPTH` change; strict semantic compile command in `tests/test_t096_public_frontend_input_modes.py` used `from_filelist(filelist=negative/design.f, source_root=negative, top="fifo_top")` followed by `build_source_catalog(...).to_report()["compile"]`; it explicitly returned `{"catalog": {"parse_errors": 0, "semantic_errors": 0}, "top_overlay": {"parse_errors": 0, "semantic_errors": 0}}`; the same Formal command with that gate exited 1 and contained `unproven` and `equiv_status -assert`
review_request: READY_FOR_REVIEW; Main Agent must independently rerun the five fixed commands, inspect only allowed-file changes, independently render and inspect all README.pdf pages, then decide ACCEPTED; sub-agent did not commit, push, or set ACCEPTED
```

## 9. 主 Agent 验收

```text
acceptance_status: ACCEPTED
acceptance_head: ee702c3bbd8f4177475f5a0d13dcbfd0579c0ee8
allowed_files: PASS；实现改动全部位于第 6 节允许文件，T092–T095 仅包含主 Agent 在 T096 建立前完成的状态同步
independent_commands: 主 Agent 独立运行第 7 节全部五条固定命令，并独立执行 `pdftoppm -png -r 120 README.pdf /tmp/t096-main-pdf.V7Wcsy/page`
independent_results: unittest exit 0，Ran 56 tests in 17.708s，OK；py_compile exit 0；PDF guard exit 0，`README.pdf pages=3 filelist_first_and_a4=pass`；`git diff --check HEAD` exit 0；READY_FOR_REVIEW guard exit 0
formal_verification: PASS；FIFO `signals` actual renamed gate 的正例 exit 0 且 JSON `formal_equivalence=pass`；固定功能负例保持 parse/semantic errors 为 0，Formal exit 1 并包含 `unproven` 与 `equiv_status -assert`
pdf_review: PASS；主 Agent 将 README.pdf 全部 3 页独立渲染到 `/tmp/t096-main-pdf.V7Wcsy` 并逐页查看，A4 页面无裁切、重叠、黑块或缺字
decision: ACCEPTED；三种公共输入模式、filelist-first 文档与现有内部流水线边界均符合冻结合同，可以进入 Git 交付
```
