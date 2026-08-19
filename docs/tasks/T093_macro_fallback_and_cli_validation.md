# T093：宏 fallback 解析、输入互斥和详细 CLI 诊断

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：待分配的 GPT-5.6 Luna Extra high 子 Agent
- 前置任务：T091 `.h` 宏头文件、T092 filelist 自动边界；当前基线 `ee14f85`
- 任务类型：SourceSet/discovery + CLI input/error adapter
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：`N/A`；本任务不改变 rewrite/mapping，也不把错误路径发布为 rewritten RTL

## 1. 单一目标

在不扩大 filelist 候选集合、不修改宏加密范围的前提下，完成以下三个紧密相关的输入适配行为：

1. 识别宏头文件中的条件 fallback，例如：

   ```systemverilog
   // stl_gmacro.h
   `ifndef STL_MCFG_W
       `define STL_MCFG_W 64
   `endif
   ```

   与另一个明确配置头文件中的：

   ```systemverilog
   // stl_gsetting_base.h
   `define STL_MCFG_W 64
   ```

   应视为一个有效 provider 组合，不得错误报告 `macro has multiple providers`。两个都无条件定义
   同一宏的文件仍必须 fail-closed；互斥条件下的定义必须继续按当前 define 环境分析。

2. 明确禁止输入模式混用：

   - filelist 与 project-root 不得同时出现；
   - single file 与 project-root 不得同时出现；
   - public filelist 与 `--source-root` 仍然非法；
   - public single file 仍必须使用 `--source-root`；
   - project-root 仍必须有 root 和 top；
   - 拒绝时不创建 output、mapping 或 metrics。

   这里同时覆盖 public `rtl_encrypt.py` 的三种模式和 internal
   `python -m rtl_obfuscator.rewrite encrypt-vnext` 的显式 `--project-root` 参数。

3. 将输入失败的可操作诊断直接输出到 CLI，不要求用户再写 Python 探针。错误保持稳定首行，
   并在有数据时至少包含：

   ```text
   error: CLI_VNEXT_INPUT_INVALID
   detail: SOURCESET_DISCOVERY_FAILED
   path: <relative source or filelist path>
   message: macro has multiple providers: STL_MCFG_W
   details: <provider list or candidate list>
   hint: <下一步建议>
   ```

   `details` 没有内容时可以省略，但 `detail`、`path`、`message` 不得因错误类型不同而被静默丢弃。

## 2. 冻结实现边界

### 2.1 宏 provider 语义

- 继续只分析 filelist 候选和显式/解析到的 include context，不扫描自动 root 下未列出的 `.sv/.v/.h`。
- `ifndef NAME` 下的 `define NAME` 标记为 fallback provider；当同一宏存在有效无条件 provider
  或 CLI predefine 时，fallback 不制造第二个 provider。
- 没有无条件 provider 时，单一 fallback 可以解析引用；多个 fallback 仍需保持歧义失败，除非
  当前预处理条件明确只激活其中一个。
- 两个或多个有效无条件 provider 即使值相同也继续失败，避免把不同工艺配置静默合并。
- 不实现完整 Verilog 宏求值器，不支持 shell、glob、宏展开文本替换或第二套 parser。
- provider 诊断必须保留相对文件路径，优先列出候选 provider；不得只给宏名。

### 2.2 输入模式矩阵

| 入口 | 合法输入 | 明确非法组合 |
| --- | --- | --- |
| public `rtl_encrypt.py` | `--input + --source-root`；`--filelist`；`--source-root + --top` | `--filelist + --source-root`；`--input +` project-root 参数 |
| internal `encrypt-vnext` | 单独 `--input`；单独 `--filelist`；单独 `--project-root` | `--filelist + --project-root`；`--input + --project-root`；三者任意多选 |

public 入口没有 `--project-root` 选项时，参数解析错误也必须继续返回稳定
`CLI_VNEXT_INPUT_INVALID`，并说明正确模式，而不是 Python traceback。

### 2.3 诊断传递

- `SourceSetError` 可以扩展结构化 `details`，并由 discovery error 映射完整传递；不得破坏已有
  `code/path/message` 属性。
- `_CliVNextError` 和公共 `_run_cli_operation` 必须保留 detail 文本；输入失败首行 code 保持不变。
- 详细诊断只能暴露项目内相对路径、宏名和候选 provider，不输出临时绝对路径或 traceback。
- 错误发生在 source discovery 前，不得创建任何输出目录或报告。

## 3. 固定 compact fixture 和测试

新增 `tests/fixtures/t093_macro_fallback/`，包含：

- 一个 `ifndef` fallback header；
- 一个显式无条件 configuration header；
- 一个 source 使用该宏；
- 两个无条件定义同一宏的歧义 header，用于固定负例；
- 一个 filelist 明确列出这些文件。

目标 unittest 必须覆盖：

1. fallback + 无条件 provider 的 SourceSet 解析成功；
2. 两个无条件 provider 仍返回 stable ambiguity，且包含 provider details；
3. public filelist/filelist+source-root、single-file/project-root 组合的稳定失败；
4. internal `encrypt-vnext` 的 `--filelist + --project-root` 与 `--input + --project-root` 稳定失败；
5. public CLI 对缺 provider/多 provider 至少一个错误路径直接输出 detail、path、message 和 details，
   且不发布 output。

不得修改既有 fixture 来制造通过；既有 T091/T092 行为必须继续保留。

## 4. 明确不包含

- 不修改 `MappingVNext`、`SymbolGraph`、rename category、restore 或 Formal 证明强度；
- 不把 `.h` 宏定义加入 rename 目标；
- 不通过自动扫描 root、忽略宏诊断、选第一个 provider 或按相同数值静默合并来规避错误；
- 不改变 internal `encrypt-vnext` 的合法单独 filelist/source-root 语义，只增加明确的互斥拒绝和诊断；
- 不删除历史测试，不修改服务器工程；
- 如需允许文件外改动或改变上述边界，必须先记录偏差并停止，不得自行扩展任务。

## 5. 允许修改

```text
README.md
docs/development/project_structure.md
docs/tasks/T093_macro_fallback_and_cli_validation.md
rtl_obfuscator/project_discovery.py
rtl_obfuscator/source_set.py
rtl_obfuscator/rewrite.py
tests/test_public_cli.py
tests/test_t093_macro_fallback_and_cli_validation.py
tests/fixtures/t093_macro_fallback/**
```

允许列表外不得修改；子 Agent 不得 commit、push 或设置 `ACCEPTED`。

## 6. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t093_macro_fallback_and_cli_validation \
  tests.test_t091_h_macro_header tests.test_t092_filelist_input_mode \
  tests.test_source_set -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project_discovery.py rtl_obfuscator/source_set.py \
  rtl_obfuscator/rewrite.py tests/test_t093_macro_fallback_and_cli_validation.py \
  tests/test_public_cli.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c \
  'from pathlib import Path; text=Path("docs/tasks/T093_macro_fallback_and_cli_validation.md").read_text(encoding="utf-8"); assert "- 状态：`READY_FOR_REVIEW`" in text; print("READY_FOR_REVIEW guard=pass")'
```

本任务属于 SourceSet/discovery + CLI adapter，Formal verification 为 `N/A`；目标测试不得把
错误路径成功加密或 identity comparison 当作 Formal 证据。禁止 blanket discovery 和 RISC-V-Vector
Formal。

## 7. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: ee14f85
preexisting_changes: docs/tasks/T093_macro_fallback_and_cli_validation.md (untracked task contract only; allowed and owned by T093)
correction_note: Main Agent review found the original success fixture included both headers from the source, so it did not exercise filelist-global provider resolution. The correction removes those source includes, asserts both headers remain explicit filelist entries, and makes the selected `.h` context available to strict closure compilation without expanding candidates.
latest_correction: public filelist infer_filelist_root failures were converted from plain str(error) to the existing structured SourceSetError -> _CliVNextError path, retaining detail, cleaned path, message, and details; a missing-filelist CLI negative was added.
changed_files:
  - README.md
  - docs/development/project_structure.md
  - docs/tasks/T093_macro_fallback_and_cli_validation.md
  - rtl_obfuscator/project_discovery.py
  - rtl_obfuscator/source_set.py
  - rtl_obfuscator/rewrite.py
  - tests/test_t093_macro_fallback_and_cli_validation.py
  - tests/fixtures/t093_macro_fallback/**
commands:
  - baseline: conda run -n rtl_obfuscation python -m unittest tests.test_t093_macro_fallback_and_cli_validation tests.test_t091_h_macro_header tests.test_t092_filelist_input_mode tests.test_source_set -v
  - target unittest: conda run -n rtl_obfuscation python -m unittest tests.test_t093_macro_fallback_and_cli_validation tests.test_t091_h_macro_header tests.test_t092_filelist_input_mode tests.test_source_set -v
  - py_compile: conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project_discovery.py rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py tests/test_t093_macro_fallback_and_cli_validation.py tests/test_public_cli.py
  - diff check: git diff --check HEAD
results: baseline exit 1; T093 test module was not present, while existing T091/T092/SourceSet tests ran 18 tests with 18 passing; latest target unittest exit 0 with 23 tests passed; py_compile exit 0; diff check exit 0; READY_FOR_REVIEW guard exit 0 with `READY_FOR_REVIEW guard=pass`
schema_or_behavior: guard-aware fallback providers; explicit public/internal mode exclusivity; CLI retains source error code/path/message/details; explicit filelist `.h` provider context is compiled before source units without entering source compile order or rename targets
boundaries: filelist candidate closure unchanged; one fallback plus one effective unconditional provider succeeds; true multiple unconditional providers remain fail-closed with provider details; public filelist + --source-root remains illegal; internal --input/--filelist + --project-root is rejected; no macro rename or rewrite/schema changes
cleanup_candidates: none
formal_verification: N/A; no rewritten RTL is produced as an accepted task behavior
review_request: Main Agent may independently rerun the fixed target unittest, py_compile, and diff check; no commit/push/ACCEPTED performed by sub-agent
```

## 8. 主 Agent 验收

```text
acceptance_status: ACCEPTED
acceptance_head: ee14f85
allowed_files: PASS; all changes are within the T093 allowlist, including the compact fixture and tests
independent_commands: `conda run -n rtl_obfuscation python -m unittest tests.test_t093_macro_fallback_and_cli_validation tests.test_t091_h_macro_header tests.test_t092_filelist_input_mode tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project_discovery.py rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py tests/test_t093_macro_fallback_and_cli_validation.py tests/test_public_cli.py`; `git diff --check HEAD`; exact READY_FOR_REVIEW guard
independent_results: unittest exit 0, Ran 23 tests, OK; py_compile exit 0; diff check exit 0; guard exit 0; global filelist fallback provider path passed, true unconditional ambiguity remained fail-closed with provider details, public and internal mode conflicts were rejected without outputs, and CLI missing/discovery errors exposed structured diagnostics
formal_verification: N/A; this task changes SourceSet/discovery and CLI diagnostics only and does not produce an accepted rewritten RTL artifact
decision: ACCEPTED; ready for Main Agent commit and push
```
