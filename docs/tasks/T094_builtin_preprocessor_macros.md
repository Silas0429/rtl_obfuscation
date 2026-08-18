# T094：内置预处理宏兼容

- 状态：`READY_FOR_REVIEW`
- 设计负责人：主 Agent
- 实现负责人：待分配的 GPT-5.6 Luna Extra high 子 Agent
- 前置任务：T093 宏 fallback、输入互斥和详细诊断；当前基线 `5f625e5`
- 任务类型：SourceSet/discovery compatibility
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：`N/A`；本任务只修正预处理宏 discovery，不改变 rewrite/mapping

## 1. 单一目标

让 filelist/project discovery 正确识别 SystemVerilog 预定义预处理宏，不再把编译器提供的宏当成
filelist provider 查找对象。当前服务器错误：

```text
macro has no provider: __FILE__
```

必须在不修改服务器 filelist、不添加伪造 `+define+__FILE__` 的情况下消失。

## 2. 冻结内置宏语义

### 2.1 内置宏集合

以下宏作为预处理环境中的内置宏处理：

```text
__FILE__
__LINE__
__DATE__
__TIME__
__TIMESTAMP__
```

- 内置宏可以出现在 source、`.svh/.vh` 或显式 `.h` context 中；
- 内置宏引用不要求 provider，不产生 `macro_edges`，不进入 filelist 候选集合；
- 内置宏参与 `ifdef/ifndef/elsif` 的条件判断，初始状态视为已定义；
- 内置宏不得被错误映射为项目文件路径；不得进入 SourceSet 的 source/include/compile order；
- 不允许用 `--define` 或 filelist entry 伪造内置宏 provider。

### 2.2 普通宏边界

- 普通项目宏的缺失、多个无条件 provider、fallback provider 规则保持 T093 行为；
- `__FILE__` 等内置宏与显式项目定义同名时，不静默选择项目定义；继续保持保守失败或记录明确的
  预处理冲突，不能把内置宏兼容扩展为任意宏忽略；
- 不新增完整 Verilog 宏求值器、宏文本展开改写、shell/vendor filelist 语法或第二套 parser；
- 不修改 `.v/.vh/.h` 后缀、filelist 自动 root、输入模式互斥和 CLI 诊断格式。

## 3. 固定 compact fixture 和测试

新增 `tests/fixtures/t094_builtin_preprocessor_macros/`：

- `design.f` 显式列出一个 source 和可选 context header；
- source 实际引用 `` `__FILE__ ``、`` `__LINE__ ``，并至少有一个条件分支证明内置宏初始已定义；
- filelist 中不提供这些宏的 `.h` 定义；
- 另有一个普通未定义宏负例，证明未知宏仍返回 `SOURCESET_DISCOVERY_FAILED`，不被泛化忽略。

目标 unittest 必须验证：

1. 内置宏 source 的 `from_filelist` discovery 成功，top/closure/compile order 正常；
2. 内置宏不出现在 `included_files`、macro dependency provider 或错误 details 中；
3. 普通未定义宏仍 fail-closed，错误包含 consumer path 和稳定 message；
4. 既有 T091/T092/T093 回归继续通过。

不需要执行成功加密、gate、decrypt 或 Formal；本任务不得通过 identity comparison 代替 Formal。

## 4. 明确不包含

- 不修改 `MappingVNext`、`SymbolGraph`、rename category、restore、rate 或 Formal；
- 不把内置宏加入 rename 目标；
- 不修改服务器工程和现有 fixture；
- 不删除旧测试或历史入口；
- 如需允许文件外改动或增加其它宏集合，先记录偏差并停止，不得自行扩大范围。

## 5. 允许修改

```text
README.md
docs/development/project_structure.md
docs/tasks/T094_builtin_preprocessor_macros.md
rtl_obfuscator/project_discovery.py
tests/test_t094_builtin_preprocessor_macros.py
tests/fixtures/t094_builtin_preprocessor_macros/**
```

允许列表外不得修改；子 Agent 不得 commit、push 或设置 `ACCEPTED`。

## 6. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t094_builtin_preprocessor_macros \
  tests.test_t091_h_macro_header tests.test_t092_filelist_input_mode \
  tests.test_t093_macro_fallback_and_cli_validation tests.test_source_set -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project_discovery.py \
  tests/test_t094_builtin_preprocessor_macros.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c \
  'from pathlib import Path; text=Path("docs/tasks/T094_builtin_preprocessor_macros.md").read_text(encoding="utf-8"); assert "- 状态：`READY_FOR_REVIEW`" in text; print("READY_FOR_REVIEW guard=pass")'
```

本任务为 SourceSet/discovery compatibility，Formal verification 为 `N/A`；禁止 blanket discovery
和 RISC-V-Vector Formal。

## 7. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 5f625e5
preexisting_changes: none
changed_files: rtl_obfuscator/project_discovery.py; tests/test_t094_builtin_preprocessor_macros.py; tests/fixtures/t094_builtin_preprocessor_macros/design.f; tests/fixtures/t094_builtin_preprocessor_macros/rtl/top.sv; tests/fixtures/t094_builtin_preprocessor_macros/unknown.f; tests/fixtures/t094_builtin_preprocessor_macros/rtl/unknown.sv; docs/tasks/T094_builtin_preprocessor_macros.md
commands: `conda run -n rtl_obfuscation python -m unittest tests.test_t094_builtin_preprocessor_macros tests.test_t091_h_macro_header tests.test_t092_filelist_input_mode tests.test_t093_macro_fallback_and_cli_validation tests.test_source_set -v` (baseline exit 1: T094 test module absent; implementation exit 0); `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project_discovery.py tests/test_t094_builtin_preprocessor_macros.py` (exit 0); `git diff --check HEAD` (exit 0); READY_FOR_REVIEW guard (pass)
results: target unittest 25/25 passed; builtin source discovery and conditional branch passed; included_files empty and builtin macro_edges empty; ordinary unknown macro remained SOURCESET_DISCOVERY_FAILED with consumer path and stable message; T091/T092/T093/SourceSet regression passed; py_compile and diff check passed
schema_or_behavior: predefined SystemVerilog macros are environment-defined and excluded from provider lookup/dependency edges; ordinary macro failures remain fail-closed; explicit project redefinition or --define of a builtin fails closed with provider details
boundaries: only project_discovery builtin macro environment and compact SourceSet tests/fixtures; no filelist, rewrite, mapping, or CLI schema changes; no server工程 or existing fixture changes
cleanup_candidates: none
formal_verification: N/A; no rewritten RTL is produced as an accepted task behavior
review_request: Main Agent may independently rerun the four fixed commands and review the allowed-file diff; sub-agent did not commit, push, or set ACCEPTED
```

## 8. 主 Agent 验收

```text
acceptance_status: ACCEPTED
acceptance_head: 5f625e5
allowed_files: PASS; only project_discovery.py, the T094 contract, compact fixture and test changed
independent_commands: `conda run -n rtl_obfuscation python -m unittest tests.test_t094_builtin_preprocessor_macros tests.test_t091_h_macro_header tests.test_t092_filelist_input_mode tests.test_t093_macro_fallback_and_cli_validation tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project_discovery.py tests/test_t094_builtin_preprocessor_macros.py`; `git diff --check HEAD`; exact READY_FOR_REVIEW guard
independent_results: unittest exit 0, Ran 25 tests, OK; py_compile exit 0; diff check exit 0; guard exit 0; `__FILE__`, `__LINE__`, `__DATE__`, `__TIME__`, and `__TIMESTAMP__` were treated as predefined with no provider/dependency edge, while ordinary unknown macro discovery remained fail-closed
formal_verification: N/A; this task changes SourceSet/discovery only and does not produce an accepted rewritten RTL artifact
decision: ACCEPTED; ready for Main Agent commit and push
```
