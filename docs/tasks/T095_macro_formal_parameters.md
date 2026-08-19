# T095：多行宏形式参数兼容

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：待分配的 GPT-5.6 Luna Extra high 子 Agent
- 前置任务：T093 宏 fallback/CLI 诊断、T094 内置预处理宏；当前基线 `f6762ea`
- 任务类型：SourceSet/discovery compatibility
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：`N/A`；本任务只修正宏依赖 discovery，不改变 rewrite/mapping

## 1. 单一目标

让 filelist discovery 正确处理服务器 `StChAssert.sv` 中的多行宏形式参数，例如：

```systemverilog
`define ASSERT_ERROR(__name) \
  $error("%s", `PRIM_STRINGIFY(__name), `__FILE__, `__LINE__)

`define ASSERT_FINAL(__name, __prop) \
  final begin \
    __name: assert (__prop) \
      else begin `ASSERT_ERROR(__name) end \
  end
```

当前实现把宏体中的 `` `__name `` 当成普通项目宏，报：

```text
macro has no provider: __name
```

宏形式参数必须只在所属宏的 replacement body 内视为局部已定义，不得要求 filelist provider。

## 2. 冻结宏形式参数语义

### 2.1 必须支持

- `` `define NAME(arg1, arg2, ...) \`` 的形式参数识别；
- 多行反斜杠续行，直到宏定义 replacement body 结束；
- 带默认值的参数，例如 `__clk = `ASSERT_DEFAULT_CLK`；
- replacement body 中以反引号引用的形式参数，例如 `` `__name ``；
- token-paste 形式，例如 `` `__name``KnownEnable ``，其中 `KnownEnable` 不是待解析宏；
- replacement body 中的其它真实宏调用仍按现有 provider 规则解析，例如 `` `ASSERT_ERROR ``、
  `` `PRIM_STRINGIFY `` 和 `` `ASSERT_DEFAULT_CLK ``；
- 多行宏中的 `ifdef/ifndef/else/endif` 继续沿用当前预处理环境和 T094 内置宏语义。

### 2.2 必须保持 fail-closed

- 同名形式参数在宏体外使用，仍视为普通未定义宏并返回 `SOURCESET_DISCOVERY_FAILED`；
- 未声明的宏参数仍必须报缺失 provider；
- 宏定义中的参数名不得加入全局 provider 集合、SourceSet included files 或 macro dependency edges；
- 不把所有双下划线标识符加入内置宏白名单；`__name` 只有在对应宏体内才是合法局部参数；
- 不新增宏文本改写、宏 rename、shell/vendor filelist 语法或第二套 parser。

## 3. 固定 compact fixture 和测试

新增 `tests/fixtures/t095_macro_formal_parameters/`：

- 一个显式 filelist；
- 一个 `.svh` 或 `.h` 宏 context，包含 `PRIM_STRINGIFY`、`ASSERT_ERROR`、`ASSERT_FINAL` 等多行
  宏，覆盖参数、默认参数、条件分支和 token-paste；
- 一个 source include 并调用这些宏，实际使用 `` `__FILE__ ``、`` `__LINE__ ``；
- 一个负例 source 在宏定义外直接使用 `` `__name `` 或另一个未声明形式参数。

目标 unittest 必须验证：

1. 正例 filelist discovery 成功，top/closure/compile order 正常；
2. 正例不产生形式参数 provider 或错误 details；
3. token-paste 的后缀不被当成宏引用；
4. 宏体外未定义参数仍 fail-closed，且保留 consumer path 和稳定 message；
5. T091/T092/T093/T094 和 SourceSet 回归继续通过。

不需要成功加密、gate、decrypt 或 Formal；本任务不得用 identity comparison 代替 Formal。

## 4. 明确不包含

- 不修改 `MappingVNext`、`SymbolGraph`、rename category、restore、rate 或 CLI 输入 schema；
- 不修改服务器工程、既有 fixture 或历史测试；
- 不把 `__name`、`__prop` 等形式参数升级为全局内置宏；
- 不删除旧入口；
- 如需修改允许文件外内容或改变宏语义，先记录偏差并停止，不得自行扩大任务。

## 5. 允许修改

```text
README.md
docs/development/project_structure.md
docs/tasks/T095_macro_formal_parameters.md
rtl_obfuscator/project_discovery.py
tests/test_t095_macro_formal_parameters.py
tests/fixtures/t095_macro_formal_parameters/**
```

允许列表外不得修改；子 Agent 不得 commit、push 或设置 `ACCEPTED`。

## 6. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t095_macro_formal_parameters \
  tests.test_t094_builtin_preprocessor_macros tests.test_t093_macro_fallback_and_cli_validation \
  tests.test_t092_filelist_input_mode tests.test_t091_h_macro_header tests.test_source_set -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project_discovery.py tests/test_t095_macro_formal_parameters.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c \
  'from pathlib import Path; text=Path("docs/tasks/T095_macro_formal_parameters.md").read_text(encoding="utf-8"); assert "- 状态：`READY_FOR_REVIEW`" in text; print("READY_FOR_REVIEW guard=pass")'
```

本任务为 SourceSet/discovery compatibility，Formal verification 为 `N/A`；禁止 blanket discovery
和 RISC-V-Vector Formal。

## 7. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: f6762ea
preexisting_changes: none
changed_files:
  - rtl_obfuscator/project_discovery.py
  - tests/test_t095_macro_formal_parameters.py
  - tests/fixtures/t095_macro_formal_parameters/design.f
  - tests/fixtures/t095_macro_formal_parameters/unknown.f
  - tests/fixtures/t095_macro_formal_parameters/rtl/asserts.h
  - tests/fixtures/t095_macro_formal_parameters/rtl/defaults.h
  - tests/fixtures/t095_macro_formal_parameters/rtl/top.sv
  - tests/fixtures/t095_macro_formal_parameters/rtl/unknown.sv
  - docs/tasks/T095_macro_formal_parameters.md
commands:
  - `conda run -n rtl_obfuscation python -m unittest tests.test_t095_macro_formal_parameters tests.test_t094_builtin_preprocessor_macros tests.test_t093_macro_fallback_and_cli_validation tests.test_t092_filelist_input_mode tests.test_t091_h_macro_header tests.test_source_set -v` (exit 0)
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project_discovery.py tests/test_t095_macro_formal_parameters.py` (exit 0)
  - `git diff --check HEAD` (exit 0)
  - READY_FOR_REVIEW guard (pending final command)
results: 28 tests passed; multiline formal parameters, defaults, conditional branches, token-paste, and outside-body fail-closed behavior verified; no existing regression in T091-T094 or SourceSet
schema_or_behavior: macro formal parameters are local to their multiline replacement body; default arguments and token-paste are preserved; ordinary outside-body macro references remain fail-closed
boundaries: only project_discovery, compact macro fixture/tests, and task record; no macro rename, filelist, CLI, mapping, or restore changes; formal parameter parsing is limited to identifier formals and balanced default expressions in define headers
cleanup_candidates: none
formal_verification: N/A; no rewritten RTL is produced as an accepted task behavior
review_request: implementation complete; ready for Main Agent independent review; no commit, push, or ACCEPTED status set
```

## 8. 主 Agent 验收

```text
acceptance_status: ACCEPTED
acceptance_head: f6762ea
allowed_files: PASS; only project_discovery.py, the T095 contract, compact fixture and test changed
independent_commands: `conda run -n rtl_obfuscation python -m unittest tests.test_t095_macro_formal_parameters tests.test_t094_builtin_preprocessor_macros tests.test_t093_macro_fallback_and_cli_validation tests.test_t092_filelist_input_mode tests.test_t091_h_macro_header tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project_discovery.py tests/test_t095_macro_formal_parameters.py`; `git diff --check HEAD`; exact READY_FOR_REVIEW guard
independent_results: unittest exit 0, Ran 28 tests, OK; py_compile exit 0; diff check exit 0; guard exit 0; multiline formal parameters, default arguments, conditional branches, token-paste, and macro-body-local provider behavior passed; outside-body `__name` remained fail-closed
formal_verification: N/A; this task changes SourceSet/discovery only and does not produce an accepted rewritten RTL artifact
decision: ACCEPTED; ready for Main Agent commit and push
```
