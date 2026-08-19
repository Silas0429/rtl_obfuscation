# T097：design-scope 局部 typedef discovery 作用域

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：GPT-5.6 Luna Extra high 子 Agent
- 前置任务：T096 filelist-first 公共前端；当前基线 `644f109`
- 任务类型：SourceSet/discovery bug fix
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：`N/A`；本任务只修正 discovery 的类型 provider 索引，不改变 rewrite/mapping

## 1. 单一目标

修复 filelist discovery 把不同 module/interface 等 design scope 内的同名局部 `typedef` 当成跨文件
全局 provider，从而错误报告：

```text
type has multiple providers: stsram_dat_bk1_t
```

服务器输入中的两个真实声明分别位于 `Memory/StChStatusBuf.sv` 和
`ReqPath/StChReqPath.sv` 的模块局部作用域；它们可以合法同名，不得形成 source dependency 或全局歧义。
真正的 compilation-unit 全局 typedef 歧义仍必须 fail-closed，并在结构化诊断中列出所有 provider 路径。

## 2. 冻结行为合同

### 2.1 局部 typedef

- 使用 PySlang syntax ownership（`parent`/ancestor）判断作用域，不得使用正则或源码文本猜测 owner；
- `TypedefDeclarationSyntax` 只要位于 module 或 interface design declaration 内，包括其下的嵌套 lexical
  scope，就属于该 design scope，不得进入跨文件 `types_by_name` provider 索引；
- 多个不同 source unit、不同 module/interface 可以声明同名局部 typedef；各自文件中的本地引用不得触发
  `type has multiple providers`；
- module 的 `parameter type NAME = ...` 是本模块的类型形参，不是跨文件 typedef provider；现有行为不得退化；
- 本任务不改变 SymbolGraph 对最终严格 compilation 中 typedef symbol 的分类、rename/preserve/unsupported
  决策；这里只修正建立 SourceSet closure 前的 provider heuristic。

### 2.2 跨文件 provider 与失败诊断

- 直接位于 compilation-unit scope 的 typedef 继续作为现有跨文件 provider，单一 provider 继续建立依赖；
- package typedef 的现有 discovery 行为保持不变；本任务不设计新的 package import resolver；
- 两个不同 physical files 提供同名 compilation-unit typedef 时继续返回：

  ```text
  code: SOURCESET_DISCOVERY_FAILED
  message: type has multiple providers: <NAME>
  details: [{"provider":"<first>"},{"provider":"<second>"}]
  ```

- provider 路径按 normalized relative path 排序、去重；公共 `rtl_encrypt.py` 必须透传 `details`，失败无
  traceback、stdout 为空且不得创建 output/mapping/metrics；
- consumer path 和现有 `CLI_VNEXT_INPUT_INVALID` / `SOURCESET_DISCOVERY_FAILED` 两层错误码保持不变。

## 3. Compact fixture 与机器可验收输出

新增 `tests/fixtures/t097_local_typedef_scope/` 和
`tests/test_t097_local_typedef_discovery_scope.py`，不得修改既有 RTL fixture。

目标测试必须覆盖：

1. 两个独立 module 和一个 interface 各自声明同名局部 `stsram_dat_bk1_t`，top 引用这些 design units；
   显式 filelist discovery 成功，top closure/compile order 稳定且严格 compilation 无错误；
2. fixture 至少包含一个同名 `parameter type`，证明它不进入跨文件 provider；
3. 一个 compilation-unit typedef provider 与 consumer discovery 成功，保持现有跨文件依赖；
4. 两个不同 source files 的同名 compilation-unit typedef 对同一 consumer 形成真正歧义；
   `SourceSetError` 的 code、path、message 和排序后的 provider details 精确匹配；
5. 同一真歧义经公共 filelist CLI 返回结构化 `details`，stdout 为空、无 traceback且输出目录不存在。

测试只验证 SourceSet/discovery；不得生成或验收改写 gate，不运行 decrypt 或 Formal。

## 4. 明确不包含

- 不修改服务器 `ChipPlatform`、用户 filelist 或其中任何 RTL；
- 不删除 `StChStatusBuf.sv`、`StChReqPath.sv` 或新加入的 `csr_if.sv`；
- 不新增 project-root 扫描、自动 provider 猜测、fallback、第二套 parser 或文本 owner 规则；
- 不改变宏、include、filelist root、compile-order、category、SymbolGraph、MappingVNext、restore 或 CLI 参数矩阵；
- 不实现 package import、class、function/task 或 compilation-unit 模式的全新作用域模型；
- 不运行 blanket unittest discovery 或 RISC-V-Vector Formal；
- 若 PySlang ownership API 无法稳定区分本合同 fixture 的 compilation-unit 与 design-scope typedef，记录偏差并
  停止，不得扩大任务。

## 5. 允许修改

```text
docs/tasks/T097_local_typedef_discovery_scope.md
rtl_obfuscator/project_discovery.py
tests/test_t097_local_typedef_discovery_scope.py
tests/fixtures/t097_local_typedef_scope/**
```

允许列表外不得修改；子 Agent 不得 commit、push 或设置 `ACCEPTED`。

## 6. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t097_local_typedef_discovery_scope -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project_discovery.py tests/test_t097_local_typedef_discovery_scope.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c \
  'from pathlib import Path; text=Path("docs/tasks/T097_local_typedef_discovery_scope.md").read_text(encoding="utf-8"); assert "- 状态：`READY_FOR_REVIEW`" in text; print("READY_FOR_REVIEW guard=pass")'
```

本任务选择 `SourceSet/discovery` 最小验收行；Formal verification 为 `N/A`，禁止用 identity comparison
或无改名 gate 伪装 Formal 证据。

## 7. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 644f10927321abf7f007885d9daaab670c7af5ac
preexisting_changes: T097 task contract only
changed_files: rtl_obfuscator/project_discovery.py; tests/test_t097_local_typedef_discovery_scope.py; tests/fixtures/t097_local_typedef_scope/**; docs/tasks/T097_local_typedef_discovery_scope.md
commands: baseline and acceptance fixed commands in section 6; baseline unittest exit 1 (expected missing test); target unittest rerun exit 0; py_compile exit 0; git diff --check HEAD exit 0
results: target unittest 4 tests OK; syntax compilation OK; diff check OK; public ambiguity emitted structured provider details with empty stdout, no traceback, and no output directory
schema_or_behavior: module/interface typedefs are excluded from global types_by_name via PySlang syntax parent ancestry; compilation-unit typedefs retain dependency and ambiguity behavior; ambiguity details are sorted normalized provider paths
boundaries: sections 2 and 4; package behavior unchanged; no rewritten RTL produced
cleanup_candidates: none
formal_verification: N/A; this task changes SourceSet/discovery only
review_request: READY_FOR_REVIEW; implementation and four fixed acceptance checks complete; Main Agent must independently rerun section 6 and decide ACCEPTED
```

## 8. 主 Agent 验收

```text
acceptance_status: ACCEPTED
acceptance_head: 644f10927321abf7f007885d9daaab670c7af5ac
allowed_files: PASS; only project_discovery.py, T097 contract, T097 target test and T097 compact fixture changed
independent_commands: Main Agent independently ran all four fixed commands in section 6
independent_results: target unittest exit 0, Ran 4 tests in 0.124s, OK; py_compile exit 0; git diff --check HEAD exit 0; READY_FOR_REVIEW guard exit 0
formal_verification: N/A; SourceSet/discovery task, no accepted rewritten RTL artifact
decision: ACCEPTED; design-scope local typedefs no longer create global provider ambiguity, compilation-unit dependency and true ambiguity remain fail-closed with provider details
```
