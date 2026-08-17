# T090：服务器 filelist 上下文指令适配

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：GPT-5.6 Luna Extra high 子 Agent
- 前置任务：T088 `.v/.vh` 加密输入支持、T089 后缀文档同步，当前基线 `8a81e2a`
- 任务类型：SourceSet/filelist 输入前端扩展；不新增重命名 category，不改变 rewrite、mapping、restore 或 Formal 语义
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：`N/A`；本任务只把 filelist 上下文收敛为 SourceSet 的 `include_dirs/defines`，不直接产生 rewritten RTL

## 1. 单一目标

在现有 `.sv/.v` source、`.svh/.vh` header、环境变量和嵌套 `-f` 支持之上，让显式 filelist
接受服务器工程中已经观察到的两类编译上下文指令：

```text
+incdir+$PROJ/aic_ss/src/stcache/include
+define+STCACHE_FEATURE
+define+DATA_WIDTH=64
```

解析结果必须继续进入唯一的
`SourceSet -> SourceCatalog -> SymbolGraph -> RewritePolicy` 流水线。filelist 指令只填充现有
`SourceSet.include_dirs` 和 `SourceSet.defines` 字段，不引入第二份编译上下文 schema。

## 2. 冻结语法和语义

### 2.1 `+incdir+`

- 支持 `+incdir+DIR`，也支持同一行用 `+` 分隔的多个目录：`+incdir+DIR1+DIR2`；
- 每个目录经过既有环境变量展开、canonical resolve 和 `--source-root` 内边界检查；
- 目录必须存在且为目录，否则返回既有 `SOURCESET_FILE_NOT_FOUND`；越出根目录返回既有
  `SOURCESET_PATH_OUTSIDE_ROOT`；未定义变量返回既有 `SOURCESET_ENV_UNDEFINED`；
- 从顶层 filelist 和嵌套 filelist 按深度优先、出现顺序收集；重复目录只保留第一次；
- 显式 CLI `--include-dir` 位于 filelist 指令之前，重复项只保留一次。

### 2.2 `+define+`

- 支持 `+define+NAME`、`+define+NAME=VALUE`，以及同一行用 `+` 分隔的多个定义；
- `NAME` 和 `VALUE` 只接受当前 CLI `--define NAME[=VALUE]` 已接受的无 shell token 形式；
- filelist 定义按深度优先、出现顺序收集；同名定义以后出现者覆盖先出现者；
- 显式 CLI `--define` 在 filelist 定义之后合并，因此 CLI 值对同名定义保持最终优先级；
- report 只记录规范化后的 `name/value`，不保留 `$PROJ` 原文。

### 2.3 文件顺序和 fail-closed 边界

- `+incdir+`、`+define+` 可以出现在 source/header 和嵌套 `-f` 之间，但上下文统一作用于整个
  当前 SourceSet；不实现按物理位置切分的局部宏作用域；
- 继续支持 T087/T088 已冻结的注释、环境变量、嵌套 `-f`、`.sv/.v/.svh/.vh` 分类、重复和 cycle
  诊断；
- `-I`、`-D`、`+libext+`、`-y`、`-v`、library map、blackbox、glob、shell 语法、工具专用选项和
  任意未知 `+...` 继续返回 `SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE`，不得静默忽略；
- 不改变 `ordered_source_files`、`included_files`、`compile_order`、top closure 或 SourceSet
  schema 版本。

## 3. 固定 compact fixture

新增 `tests/fixtures/t090_filelist_context/`，至少包含：

```text
tests/fixtures/t090_filelist_context/
├── design.f
├── nested/child.f
├── include/
├── rtl/top.v
└── rtl/child.sv
```

`design.f` 使用 `$T090_PROJ`，顶层和嵌套 filelist 分别提供 `+incdir+` 与 `+define+`，并列出
混合 `.v/.sv` source 及一个 `.vh` header。测试通过 `mock.patch.dict` 固定环境，不读取服务器
工程，也不修改用户工程。

## 4. 机器可检查结果

目标测试必须证明：

1. 混合 `.v/.sv` filelist 可被读取，source/header 顺序和 T088 行为不变；
2. 顶层与嵌套 filelist 的 include 目录按深度优先顺序规范化、去重并进入 report；
3. 顶层与嵌套 filelist 的宏定义按出现顺序覆盖，显式 CLI 参数对同名项最终优先；
4. `$NAME`、`${NAME}`、不存在目录、越根目录和未知指令均返回稳定错误码；
5. 生成的 SourceSet report 不含 `$T090_PROJ` 或其它 filelist 原始 directive 文本，且
   `ordered_source_files/compile_order/top_closure_files` 与基线语义一致；
6. T087/T088 现有 filelist 测试继续通过。

## 5. 明确不包含

- 不重新实现 `.v/.vh` 后缀支持；该行为由 T088 提供；
- 不修改 `rtl_files.py`、`project_discovery.py` 的 parser 语义、SymbolGraph、RewritePolicy、
  MappingVNext、rewrite、restore、Formal 或 CLI 模式判定；
- 不支持任意 EDA 工具的完整 filelist 方言，不解析 shell，不访问真实服务器工程；
- 不修改历史任务合同、现有 T087/T088 fixture、旧测试或脚本；
- 不创建后续拆分任务。本合同内的普通实现、测试和文档修正必须一次完成；若发现需要超出允许
  文件或改变 schema，记录偏差并停止等待主 Agent。

## 6. 允许修改

```text
README.md
docs/tasks/T090_filelist_context_directives.md
rtl_obfuscator/source_set.py
tests/test_source_set.py
tests/test_t090_filelist_context.py
tests/fixtures/t090_filelist_context/**
```

允许列表外不得有修改；子 Agent 不得 commit 或 push。

## 7. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t090_filelist_context tests.test_source_set -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/source_set.py tests/test_source_set.py \
  tests/test_t090_filelist_context.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c \
  'from pathlib import Path; text=Path("docs/tasks/T090_filelist_context_directives.md").read_text(encoding="utf-8"); assert "- 状态：`READY_FOR_REVIEW`" in text; print("READY_FOR_REVIEW guard=pass")'
```

## 8. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 8a81e2a
changed_files: README.md; docs/tasks/T090_filelist_context_directives.md; rtl_obfuscator/source_set.py; tests/test_t090_filelist_context.py; tests/fixtures/t090_filelist_context/**
commands:
  - conda run -n rtl_obfuscation python -m unittest tests.test_t090_filelist_context tests.test_source_set -v (baseline before implementation; exit 1 because the new test module was absent, existing SourceSet tests passed)
  - conda run -n rtl_obfuscation python -m unittest tests.test_t090_filelist_context tests.test_source_set -v (exit 0; 14 tests passed)
  - conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py tests/test_source_set.py tests/test_t090_filelist_context.py (exit 0)
  - git diff --check HEAD (exit 0)
  - conda run -n rtl_obfuscation python -c 'from pathlib import Path; text=Path("docs/tasks/T090_filelist_context_directives.md").read_text(encoding="utf-8"); assert "- 状态: `READY_FOR_REVIEW`" in text; print("READY_FOR_REVIEW guard=pass")' (exit 0)
results: +incdir+ and +define+ parse successfully across nested filelists; environment forms, include-dir validation, duplicate directory removal, define override, CLI final precedence, mixed .v/.sv/.vh ordering, and stable negative codes are covered; T087 SourceSet tests remain green
schema_or_behavior: only existing SourceSet.include_dirs and SourceSet.defines are populated; filelist source/header ordering, compile_order, top closure, and schema_version remain unchanged
boundaries: only single-line +incdir+ and +define+ forms are supported; no local macro scope, -I/-D, +libext+, library/tool options, glob, shell syntax, or unknown + directives; a context-only filelist retains the historical unsupported-directive error required by T087
cleanup_candidates: none
formal_verification: N/A
review_request: READY_FOR_REVIEW; exact guard exit 0; Main Agent independent review passed
```

## 9. 主 Agent 验收

```text
acceptance_status: ACCEPTED
acceptance_head: 8a81e2a
allowed_files: PASS; only README.md, this contract, rtl_obfuscator/source_set.py, the T090 test, and the T090 fixture changed
independent_commands: `conda run -n rtl_obfuscation python -m unittest tests.test_t090_filelist_context tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py tests/test_source_set.py tests/test_t090_filelist_context.py`; `git diff --check HEAD`; exact READY_FOR_REVIEW guard
independent_results: unittest exit 0, Ran 14 tests, OK; py_compile exit 0; diff check exit 0; READY_FOR_REVIEW guard exit 0
formal_verification: N/A；本任务只扩展 SourceSet 输入上下文，不产生 rewritten RTL
decision: ACCEPTED
```
