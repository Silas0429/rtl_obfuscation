# T098：authoritative filelist 直接 PySlang 编译

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：GPT-5.6 Luna Extra high 子 Agent
- 前置任务：T087–T097 filelist compatibility；当前基线 `a75a813`
- 任务类型：filelist adapter migration
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：必须复用 T096 FIFO `signals` actual gate 的正例和固定功能负例

## 1. 单一目标

将显式 filelist 收缩为 authoritative closed world：完成路径、环境变量、嵌套 `-f`、include-dir、define
和物理文件规范化后，按用户 source 顺序把完整输入直接交给 PySlang；提供 `--top` 时从同一次完整语义
编译中提取 selected-top closure，不再调用自定义 macro/type/module provider discovery 来决定 filelist
能否编译。

```text
explicit filelist
  -> normalize paths/context
  -> PySlang compile all listed source units in filelist order
  -> optional semantic selected-top closure
  -> SourceSet -> existing SourceCatalog/SymbolGraph/rewrite pipeline
```

project-root 仍负责自动寻找候选文件和依赖；本任务不得删除其现有 discovery。single-file 公共合同保持不变。

## 2. 冻结输入与编译合同

### 2.1 filelist 是唯一输入闭包

- `from_filelist()` 的 `ordered_source_files` 和 `compile_order` 必须严格等于展开后的 `.sv/.v` filelist
  顺序；不得按路径、依赖或 top 重新排序、添加或删除 source；
- 候选范围只来自 filelist、嵌套 filelist、其显式 `.svh/.vh/.h` 和可解析 include closure；不得扫描
  source root 中未列出的 `.sv/.v`；
- `.h` 继续是 context-only 物理输入：按 filelist 首次出现顺序置于 PySlang source units 之前提供宏上下文，
  但不进入 `ordered_source_files`、`compile_order` 或 canonical `design.f`，也不成为 rename target；
- `.svh/.vh` 继续通过 `` `include`` 解析，不作为独立 source unit；显式列出的 header/context 继续进入
  `included_files`、manifest、gate 和 restore；
- `+incdir+`、`+define+` 和 CLI `--include-dir/--define` 继续规范化后传入 PySlang；
- filelist 无 top 时也使用完整 PySlang catalog compilation，`top_closure_files=()`；
- filelist 有 top 时仍编译全部 listed source，`top` 只选择 elaboration overlay 和 ABI closure，不缩减输入。

### 2.2 禁止 filelist 前置 provider 推断

显式 filelist 路径不得调用 `_ProjectContext` 的下列 provider/closure 步骤：

```text
add_preprocessor_dependencies
add_type_dependencies
expand_hierarchy
```

因此 filelist 不再自行产生以下 heuristic 诊断：

```text
macro has no provider
macro has multiple providers
type has multiple providers
reachable definition not found
```

宏重定义、内置宏、宏形式参数、局部 typedef、package/type binding、module/interface resolution 和条件分支
全部由完整 PySlang compilation 按实际输入上下文决定。不得用新的名称白名单、fallback 或另一套扫描器替代旧规则。

project-root 可以继续调用现有 provider discovery；本任务不改变 project-root 的候选搜索和 compile order。

### 2.3 共享 PySlang 语义上下文

- SourceSet filelist validation 与后续 `SourceCatalog` 必须使用同一种 source/context 顺序、include dirs、defines
  和 SystemVerilog frontend 选项；不得出现 SourceSet 能编译而 SourceCatalog 因遗漏显式 `.h` context 失败；
- 可以在 `project_discovery.py` 中提取一个不依赖 `SourceSet` 的内部 shared compile helper，供
  `source_set.py` 与 `source_catalog.py` 复用；不得新增第二套 parser 或复制 SymbolGraph；
- PySlang catalog compilation 必须包含全部 listed source；selected-top overlay 从该 closed world elaboration；
- `top_closure_files` 使用 PySlang 绑定后的语义对象来源计算，并保持 filelist source 顺序。至少包括 reachable
  module/interface definition files 和 reachable expression/type 所绑定的 compilation-unit/package typedef 文件，
  排除未从 top 可达的 source；
- SourceCatalog 现有 module owner、top boundary、ABI 与 strict diagnostic 语义不得改变。

## 3. 失败与结构化诊断

- filelist 路径、环境变量、重复文件和不支持 directive 的现有 `SourceSetError` 保持；
- PySlang parse/semantic 失败继续映射为 `SOURCESET_DISCOVERY_FAILED`，但 message 固定指出
  `filelist PySlang compilation contains parse errors` 或
  `filelist PySlang compilation contains semantic errors`；
- `path` 为排序后第一个 error diagnostic 的 root-relative source path；`details` 至少包含各 error 的
  `code`、`path` 和 `start`，按 `(path, start, code)` 排序；
- top 不存在或不是唯一 module 时继续映射现有 `SOURCESET_TOP_NOT_FOUND` / `SOURCESET_TOP_AMBIGUOUS`；
- 公共 CLI 透传 detail/path/message/details，无 traceback、stdout 为空，并在失败时不创建 output、mapping、metrics；
- 不得捕获 PySlang error 后继续发布部分 SourceSet 或 gate。

## 4. Compact fixture 与目标验收

新增 `tests/fixtures/t098_authoritative_filelist/` 和
`tests/test_t098_authoritative_filelist.py`，不得修改既有 RTL fixture，除第 6 节明确允许同步的旧断言。

fixture 必须包含：

- 故意非路径排序的 source filelist；
- 在 source 条目之后显式列出的 `.h` context，source 实际使用其中宏；
- reachable module、interface、compilation-unit 或 package typedef provider；
- 一个不在 selected-top closure 中但本身可严格编译的 listed source；
- 一个引用未列 module/interface 的负例 filelist。

目标 unittest 必须验证：

1. filelist 无 top/有 top 均保持全部 listed source 原顺序，前者 closure 为空，后者 semantic closure 精确且
   排除 unused；
2. 显式 `.h` context 在 SourceSet validation 和 `build_source_catalog()` 两处均生效，catalog/top-overlay
   parse/semantic errors 都为 0；
3. monkeypatch `_ProjectContext.add_preprocessor_dependencies`、`add_type_dependencies` 和
   `expand_hierarchy` 为立即失败时，filelist 无 top/有 top 仍成功，证明旧 provider path 未被调用；
4. missing listed dependency 由 PySlang semantic diagnostic 失败，错误中没有旧
   `reachable definition not found`/macro/type provider message，并且公共 CLI 不产生输出；
5. T093 的重复宏 provider、T094 built-in、T095 多行宏参数和 T097 局部 typedef 按 PySlang 结果更新：
   不再断言 filelist 自定义 provider scanner；真正的 PySlang error 仍 fail-closed；不得删除测试；
6. T096 FIFO filelist actual renamed gate 继续 strict compile、direct restore byte-identical；Formal 正例 exit 0
   且 JSON `formal_equivalence=pass`，固定可编译功能负例 Formal 非零并包含 `unproven` 与
   `equiv_status -assert`。

## 5. 明确不包含

- 不修改服务器 `ChipPlatform`、用户 filelist 或任何真实 RTL；
- 不增加 vendor `-y/-v/+libext`、library map、shell、glob、blackbox 或 generated-source 支持；
- 不改变三种公共 CLI 参数矩阵、19 category、SymbolGraph、RewritePolicy、MappingVNext、rate、restore schema；
- 不删除 project-root discovery、T093–T097 历史任务记录或任何测试；
- 不让 filelist 回退为 source-root 扫描，不为 missing definition 猜测未列文件；
- 不运行 blanket unittest discovery 或 RISC-V-Vector Formal；
- 若 PySlang 无法从 compact fixture 的 selected top 稳定定位 reachable module/interface/type source，子 Agent
  必须记录 API 证据并停止，不得以全部 listed source 冒充 top closure。

## 6. 允许修改

```text
docs/development/project_structure.md
docs/tasks/T098_authoritative_filelist_pyslang.md
rtl_obfuscator/project_discovery.py
rtl_obfuscator/source_set.py
rtl_obfuscator/source_catalog.py
tests/test_t098_authoritative_filelist.py
tests/fixtures/t098_authoritative_filelist/**
tests/test_source_set.py
tests/test_t091_h_macro_header.py
tests/test_t092_filelist_input_mode.py
tests/test_t093_macro_fallback_and_cli_validation.py
tests/test_t094_builtin_preprocessor_macros.py
tests/test_t095_macro_formal_parameters.py
tests/test_t097_local_typedef_discovery_scope.py
```

只允许同步被 authoritative PySlang 行为替换的旧断言，不得删除 test method、放宽 fail-closed 或修改旧 fixture。
允许列表外不得修改；子 Agent 不得 commit、push 或设置 `ACCEPTED`。

## 7. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t098_authoritative_filelist tests.test_source_set \
  tests.test_t091_h_macro_header tests.test_t092_filelist_input_mode \
  tests.test_t093_macro_fallback_and_cli_validation tests.test_t094_builtin_preprocessor_macros \
  tests.test_t095_macro_formal_parameters tests.test_t097_local_typedef_discovery_scope \
  tests.test_t096_public_frontend_input_modes -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project_discovery.py rtl_obfuscator/source_set.py rtl_obfuscator/source_catalog.py \
  tests/test_t098_authoritative_filelist.py tests/test_source_set.py \
  tests/test_t091_h_macro_header.py tests/test_t092_filelist_input_mode.py \
  tests/test_t093_macro_fallback_and_cli_validation.py tests/test_t094_builtin_preprocessor_macros.py \
  tests/test_t095_macro_formal_parameters.py tests/test_t097_local_typedef_discovery_scope.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c \
  'from pathlib import Path; text=Path("docs/tasks/T098_authoritative_filelist_pyslang.md").read_text(encoding="utf-8"); assert "- 状态：`READY_FOR_REVIEW`" in text; print("READY_FOR_REVIEW guard=pass")'
```

第一条中的 T096 测试是本任务唯一 actual-gate Formal 证据；禁止额外运行 RISC 或 blanket regression。

## 8. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: a75a813a1bcc247ca4bc0315a5b26a97e8a617ee
preexisting_changes: docs/tasks/T098_authoritative_filelist_pyslang.md (active contract only)
changed_files: docs/development/project_structure.md; docs/tasks/T098_authoritative_filelist_pyslang.md; rtl_obfuscator/project_discovery.py; rtl_obfuscator/source_set.py; rtl_obfuscator/source_catalog.py; tests/test_t098_authoritative_filelist.py; tests/fixtures/t098_authoritative_filelist/**; tests/test_source_set.py; tests/test_t091_h_macro_header.py; tests/test_t093_macro_fallback_and_cli_validation.py; tests/test_t094_builtin_preprocessor_macros.py; tests/test_t095_macro_formal_parameters.py; tests/test_t097_local_typedef_discovery_scope.py
review_correction: 2026-08-19 18:30:04 +0800; Main Agent rejected first review because authoritative filelist checked PySlang semantic diagnostics before mapping a missing top, yielding SOURCESET_DISCOVERY_FAILED instead of the frozen SOURCESET_TOP_NOT_FOUND contract; correction was limited to top-not-found mapping and regression coverage. 2026-08-19 second review correction; Main Agent confirmed compiled.compilation.getDefinitions() is the authoritative native API for duplicate top definitions; correction is limited to DefinitionKind.Module top cardinality and T098-owned fixtures/tests
commands: prior review reproduction/target/fixed commands; second review native Definition API probe; second correction fixed unittest; second correction fixed py_compile; second correction fixed `git diff --check HEAD`; second correction READY_FOR_REVIEW guard
results: prior correction passed 41 tests and fixed top-not-found mapping; native Definition API probe found 2 duplicate `DefinitionKind.Module` definitions; second correction fixed unittest exit 0, Ran 42 tests in 4.062s, OK; second correction py_compile exit 0; second correction diff check exit 0; second correction guard exit 0, `READY_FOR_REVIEW guard=pass`
schema_or_behavior: filelist compiles exactly listed source order plus explicit .h context through shared PySlang helper; no _ProjectContext provider calls; top closure comes from bound module/type objects and excludes unused; diagnostics expose code/path/start; top cardinality uses compiled.compilation.getDefinitions() filtered to the requested name and DefinitionKind.Module; 0/1/>1 native module definitions map to TOP_NOT_FOUND/semantic-or-closure processing/TOP_AMBIGUOUS respectively
boundaries: sections 2, 3 and 5; top definition cardinality is native PySlang only; interface/non-module-only names map to SOURCESET_TOP_NOT_FOUND; project-root ambiguity path remains unchanged
cleanup_candidates: none; old tests may update assertions but may not be deleted
formal_verification: PASS via the fixed T096 test only; reused FIFO actual renamed gate evidence with gold `rtl_samples/example_fifo/design.f` / root `rtl_samples/example_fifo`, gate temporary `design.f` / runtime gate root, top `fifo_top`; positive Formal exited 0 with JSON `formal_equivalence=pass`; fixed functional negative remained strict-compile clean (catalog/top parse and semantic errors 0/0) and Formal exited 1 containing `unproven` and `equiv_status -assert`
review_request: second correction READY_FOR_REVIEW; exact status guard exit 0, `READY_FOR_REVIEW guard=pass`; Main Agent must independently rerun the four fixed commands and inspect allowed-file diff before deciding ACCEPTED
```

## 9. 主 Agent 验收

```text
acceptance_status: ACCEPTED
acceptance_head: a75a813a1bcc247ca4bc0315a5b26a97e8a617ee
allowed_files: PASS; all modified and added paths are listed in section 6, with no old fixture modification or test deletion
independent_commands: all four fixed commands in section 7, run by Main Agent on 2026-08-19
independent_results: unittest exit 0, Ran 42 tests in 4.085s, OK; py_compile exit 0; git diff --check HEAD exit 0; READY_FOR_REVIEW guard exit 0
formal_verification: PASS; fixed T096 actual renamed FIFO gate returned formal_equivalence=pass, and the strict-compilable functional negative returned nonzero with unproven and equiv_status -assert
decision: ACCEPTED; authoritative filelist no longer invokes custom macro/type/module provider discovery, preserves listed source order, shares one PySlang compilation contract with SourceCatalog, and maps native top cardinality to stable SourceSet errors
```
