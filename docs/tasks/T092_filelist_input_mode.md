# T092：filelist 模式禁止外部 source-root 并自动推导输入边界

- 状态：`READY_FOR_REVIEW`
- 设计负责人：主 Agent
- 实现负责人：GPT-5.6 Luna Extra high 子 Agent
- 前置任务：T087 filelist 前端兼容、T088 `.v/.vh`、T090 上下文指令、T091 `.h` 宏头文件；当前基线 `555d906`
- 任务类型：adapter migration + compact end-to-end gate/Formal
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：必须使用现有 compact fixture 完成一次 actual renamed gate 正例和一次固定功能负例

## 1. 单一目标

修正公共 `rtl_encrypt.py` 的输入模式边界：

```text
filelist 模式：--filelist FILELIST [--top TOP] [其它编译上下文] --output-dir OUT
```

在公共 filelist 模式中，用户不得再提供 `--source-root`；同时工具必须根据 filelist、嵌套
filelist、环境变量展开后的物理 entry 和 include 目录，推导内部使用的 source-root 边界，完成
现有 SourceSet、加密、gate 发布和恢复流程。

公共单文件模式仍必须提供 `--input` 与 `--source-root`；公共 project-root 模式仍必须同时提供
`--source-root` 与 `--top`。内部 `python -m rtl_obfuscator.rewrite encrypt-vnext` 的历史参数契约
不在本任务中迁移，但其 filelist 行为不得被破坏。

## 2. 冻结输入和行为

### 2.1 公共 CLI 参数矩阵

| 输入 | `--source-root` | `--top` | 结果 |
| --- | --- | --- | --- |
| `--input` | 必须 | 可选 | 接受 |
| `--filelist` | 禁止 | 可选 | 接受；root 自动推导 |
| 无 `--input/--filelist` | 必须 | 必须 | project-root，接受 |
| `--filelist` + `--source-root` | 非法 | 任意 | `CLI_VNEXT_INPUT_INVALID`，不创建输出 |

filelist 与 `--input`、project-root 以及 `--project-root` 的混用继续稳定失败。filelist 模式
缺少必要输入、文件不存在、路径越过推导边界、空 filelist、重复/cycle 或不支持的 directive
继续 fail-closed，不能降级为 project-root 扫描。

### 2.2 root 推导语义

- 顶层 filelist 使用命令当前工作目录解析；嵌套 `-f` 的相对路径相对于包含它的 filelist 所在目录。
- filelist 中的相对 source/header entry 和 `+incdir+` 相对目录相对于当前 filelist 所在目录。
- `$NAME` 与 `${NAME}` 在 filelist 中按当前环境展开；展开后的绝对路径直接参与推导。
- 自动 root 是顶层 filelist 所在目录、所有已展开物理 source/header entry 和 include 目录的共同祖先；
  推导结果必须足以保持现有 source-set 的越根保护和输出目录重叠保护。
- 推导只服务于路径规范化和分析边界；filelist 仍是 source 顺序和显式 context 的唯一输入，禁止
  因自动 root 再次把 root 下无关 source/header 扫入 filelist 候选集合。
- 显式 filelist 列出的 `.sv/.v/.svh/.vh/.h`、环境变量、嵌套 `-f`、`+incdir+`、`+define+`
  以及四个 `.h` 宏 provider 的既有语义保持不变。

### 2.3 输出和错误

- 成功时公共 CLI 的 JSON summary、mapping/source-set schema、gate 文件、direct restore 和
  byte-identical 结果保持既有行为。
- `--filelist ... --source-root ...` 必须在输入校验阶段失败，首行稳定为
  `error: CLI_VNEXT_INPUT_INVALID`，且不得创建 gate、mapping 或 metrics。
- 错误 hint 必须明确指出 filelist 模式不应提供 `--source-root`，不能继续误导为
  “project-root 模式必须同时提供 --source-root 与 --top”。

## 3. 固定 compact 验证

复用 `tests/fixtures/t091_h_macro_header/`，不修改 fixture。目标测试必须覆盖：

1. 不带 `--source-root` 的公共 filelist 加密成功，`.h` 仍是 included context，不进入
   `compile_order`，不产生 rename edit；
2. 带 `--source-root` 的公共 filelist 在输入校验阶段失败且输出目录不存在；
3. 环境变量、嵌套 filelist、相对 entry、include directory 和显式 `.h` provider 的 root 推导
   至少有一个黑盒覆盖；
4. 成功 gate 严格编译、direct restore 通过，`.h` 和 source 均 byte-identical 恢复；
5. actual-gate Formal 正例退出码为 0，JSON 包含 `"formal_equivalence":"pass"`；
6. 固定将 gate 中一个普通 signal RHS 的 `^` 改为 `|`，严格编译仍成功但 Formal 非零失败，
   并保留 `unproven` 与 `equiv_status -assert` 证据。

现有直接调用公共 `rtl_encrypt.py --filelist` 的测试，只删除不再合法的 `--source-root` 参数；
内部 `encrypt-vnext` 测试保留原参数。不得通过修改 fixture、放宽诊断或新增兼容分支制造通过。

## 4. 明确不包含

- 不改变单文件、project-root 或内部 `encrypt-vnext` 的参数契约；
- 不新增 v1/v2/v3/v4 兼容写入、第二套 filelist parser、glob、shell 或 vendor 语法；
- 不把自动 root 模式变成 project-root 自动发现；
- 不修改 SymbolGraph owner/category、MappingVNext schema、rewrite category、restore API 或
  Formal 证明强度；
- 不修改服务器工程、不改 T091 fixture、不删除测试；
- 不扩展到宏加密；`.h` 仍是只读 context provider；
- 普通实现、测试、文档和 Formal 失败必须在本合同内修正；只有需要允许文件外改动或改变上述
  边界时才记录偏差并停止等待主 Agent。

## 5. 允许修改

```text
README.md
docs/development/project_structure.md
docs/tasks/T092_filelist_input_mode.md
rtl_obfuscator/rewrite.py
rtl_obfuscator/source_set.py
tests/test_public_cli.py
tests/test_t078_direct_restore_headers.py
tests/test_t079_parameter_default_occurrence.py
tests/test_t080_expression_sized_cast_parameter.py
tests/test_t081_enum_lexical_completeness_firewall.py
tests/test_t082_function_end_label.py
tests/test_t083_named_function_argument.py
tests/test_t084_struct_pattern_field.py
tests/test_t085_typedef_lexical_completeness_firewall.py
tests/test_t088_verilog_suffix.py
tests/test_t091_h_macro_header.py
tests/test_t092_filelist_input_mode.py
```

允许列表外不得修改；子 Agent 不得 commit 或 push。

## 6. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t092_filelist_input_mode tests.test_t091_h_macro_header \
  tests.test_t088_verilog_suffix tests.test_source_set -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rewrite.py rtl_obfuscator/source_set.py \
  tests/test_t092_filelist_input_mode.py tests/test_t091_h_macro_header.py \
  tests/test_t088_verilog_suffix.py tests/test_source_set.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c \
  'from pathlib import Path; text=Path("docs/tasks/T092_filelist_input_mode.md").read_text(encoding="utf-8"); assert "- 状态：`READY_FOR_REVIEW`" in text; print("READY_FOR_REVIEW guard=pass")'
```

目标 unittest 自己执行并记录 compact Formal 正负例的 gold、gate、top、完整命令、退出码和
JSON/失败证据。主 Agent 必须独立重跑以上四条命令；不运行 blanket discovery，不运行 RISC-V-Vector
Formal，不叠加历史 acceptance driver。

## 7. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 555d906cb0ba8580b4895b0469cfb460f622b45e
preexisting_changes: docs/tasks/T092_filelist_input_mode.md (task contract, pre-existing and allowed); no unrelated user changes
changed_files: README.md; docs/development/project_structure.md; rtl_obfuscator/rewrite.py; rtl_obfuscator/source_set.py; tests/test_public_cli.py; tests/test_t078_direct_restore_headers.py; tests/test_t079_parameter_default_occurrence.py; tests/test_t080_expression_sized_cast_parameter.py; tests/test_t081_enum_lexical_completeness_firewall.py; tests/test_t082_function_end_label.py; tests/test_t083_named_function_argument.py; tests/test_t084_struct_pattern_field.py; tests/test_t085_typedef_lexical_completeness_firewall.py; tests/test_t088_verilog_suffix.py; tests/test_t091_h_macro_header.py; tests/test_t092_filelist_input_mode.py; docs/tasks/T092_filelist_input_mode.md
commands: `conda run -n rtl_obfuscation python -m unittest tests.test_t092_filelist_input_mode tests.test_t091_h_macro_header tests.test_t088_verilog_suffix tests.test_source_set -v` (exit 0); `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite.py rtl_obfuscator/source_set.py tests/test_t092_filelist_input_mode.py tests/test_t091_h_macro_header.py tests/test_t088_verilog_suffix.py tests/test_source_set.py` (exit 0); `git diff --check HEAD` (exit 0)
results: 24 tests passed; compact public filelist encryption, nested/environment/relative entry and +incdir+ root derivation, illegal source-root rejection, restore, and no-publish failure all passed. Existing T088/T091/source-set behavior and migrated public filelist calls passed.
schema_or_behavior: public filelist rejects --source-root before output creation; without it, one shared filelist parser resolves top/nested paths relative to the containing list, expands environment variables and +incdir+, derives a common internal boundary, and keeps the candidate universe bounded to filelist entries plus named include headers. Single-file, project-root, and internal encrypt-vnext contracts remain unchanged.
boundaries: no project-root scan from auto root; no second filelist parser; no macro rename; no fixture/schema/category/parser-language/Formal-strength changes; explicit source_root API behavior remains source-root-based for internal/history callers.
cleanup_candidates: none
formal_verification: PASS. Gold=`tests/fixtures/t091_h_macro_header/design.f`, top=`t091_top`, seq=`5`; actual gate was generated by `tests.test_t092_filelist_input_mode` under a temporary directory and used its generated `design.f`. Positive command: `python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t091_h_macro_header/design.f --gold-root tests/fixtures/t091_h_macro_header --gate-filelist <temporary>/gate/design.f --gate-root <temporary>/gate --top t091_top --seq 5`, exit 0, JSON contained `{"formal_equivalence":"pass","top":"t091_top","seq":5}`. Fixed negative copied that actual gate, changed one `^` RHS to `|`, strict `iverilog -g2012 -t null` exit 0, Formal exit nonzero with `unproven` and `equiv_status -assert`.
review_request: READY_FOR_REVIEW; please independently rerun the four contract commands, inspect the allowed-file diff, and decide ACCEPTED.
```

## 8. 主 Agent 验收

```text
acceptance_status: ACCEPTED
acceptance_head: 555d906
allowed_files: PASS; all changed files are listed in the T092 allowlist; no fixture or unrelated file changed
independent_commands: `conda run -n rtl_obfuscation python -m unittest tests.test_t092_filelist_input_mode tests.test_t091_h_macro_header tests.test_t088_verilog_suffix tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite.py rtl_obfuscator/source_set.py tests/test_t092_filelist_input_mode.py tests/test_t091_h_macro_header.py tests/test_t088_verilog_suffix.py tests/test_source_set.py`; `git diff --check HEAD`; exact READY_FOR_REVIEW guard
independent_results: unittest exit 0, Ran 24 tests, OK; py_compile exit 0; diff check exit 0; guard exit 0; public filelist without source-root passed auto-root/nested/environment/+incdir/restore/no-publish checks; public filelist with source-root failed with CLI_VNEXT_INPUT_INVALID before output creation
formal_verification: PASS; compact actual renamed gate used the T091 `.h` provider fixture, top t091_top, positive exit 0 with formal_equivalence=pass, and fixed functional negative exit 1 with unproven/equiv_status -assert
decision: ACCEPTED; ready for Main Agent commit and push
```
