# T087：filelist 环境变量与嵌套 `-f` 输入适配

- 状态：`READY_FOR_REVIEW`
- 设计负责人：主 Agent
- 实现负责人：待分配
- 前置任务：T086 `ACCEPTED`
- 任务类型：SourceSet 输入前端扩展；不新增重命名 category，不改变 rewrite/mapping/restore/F​​ormal 语义
- 设计依据：[`three_mode_refactor_plan.md`](../development/architecture/three_mode_refactor_plan.md)、[`T039_sourceset_input_contract.md`](T039_sourceset_input_contract.md)
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：`N/A`；本任务只扩展 SourceSet 输入解析，不生成 rewritten RTL

## 1. 单一目标

在不读取或修改实际服务器工程的前提下，为显式 `filelist` 增加一层可审计的输入展开能力，支持实际工程中已经观察到的以下写法：

```text
$PROJ/path/to/source.sv
-f $PROJ/path/to/child.f
// 注释掉的 source 或 -f
# 注释
/absolute/path/inside/source-root.sv
```

展开结果必须继续进入现有 `SourceSet -> SourceCatalog -> SymbolGraph -> RewritePolicy -> gate/restore` 唯一流水线。
本任务不修改实际工程源码，也不要求用户提供真实工程的完整 filelist 树；测试使用仓库内最小 SystemVerilog fixture 模拟这些输入形状。

## 2. 当前问题与冻结背景

T039 已冻结的原始 filelist 入口只接受空行、`#` 开头注释和 source-root-relative `.sv/.svh`；当前
`rtl_obfuscator/source_set.py` 会把每个其他非空行直接交给路径规范化，因此：

- `$PROJ/...` 不会展开为环境变量；
- `-f child.f` 不会递归读取 child filelist；
- `//...` 和 `//-f ...` 不会被识别为注释；
- source-root 内的绝对路径会在现有 T039 合同下被拒绝。

T087 将明确扩大 filelist 语法边界，但不改变后续 SourceSet schema、文件顺序和 gate 输出合同。

## 3. 固定输入语法

### 3.1 可接受行

filelist 按物理行从上到下解析，保留展开后的 source 顺序。支持：

1. 空行；
2. 首个非空字符为 `#` 的整行注释；
3. 首个非空字符为 `//` 的整行注释；
4. 一个 source/header 路径 token，后缀必须为 `.sv` 或 `.svh`；
5. `-f <filelist-path>`，其中 `-f` 与路径必须是同一行的两个 token；
6. 路径中的 `$NAME` 和 `${NAME}` 环境变量引用；
7. 绝对路径，但规范化后必须位于 `--source-root` 内。

允许路径行尾存在空白。T087 不执行 shell，不支持命令替换、通配符展开或任意 shell 表达式。

### 3.2 路径基准

为保持 T039 已验收的输入合同，展开后的相对 source/header 路径继续以 `--source-root` 为基准；
嵌套 filelist 的 `-f` 路径也必须最终解析到同一 `source-root` 内。环境变量展开后的绝对路径和直接写出的绝对路径统一做 canonical resolve，再转为 source-root-relative POSIX 路径。

本任务不引入“按当前 `.f` 所在目录解释相对路径”的第二套隐式规则。若实际工程需要该规则，必须另建任务并冻结与 T039 的兼容决策。

### 3.3 环境变量

- 变量值来自进程环境快照，不读取 shell 配置文件；
- 支持 `$PROJ` 和 `${PROJ}` 两种形式；
- 未定义变量不得保留为字面量继续解析，必须返回稳定的
  `SOURCESET_ENV_UNDEFINED`；
- 展开后路径不存在，返回既有 `SOURCESET_FILE_NOT_FOUND`；
- 展开后路径越出 source-root，返回既有 `SOURCESET_PATH_OUTSIDE_ROOT`；
- 环境变量值不得写入持久化 vNext/restore report，report 只保留规范化后的 portable SourceSet
  字段；T039 已冻结的 `SourceSet.to_report()` 绝对 `source_root` 字段保持不变，不视为新增的
  filelist 路径泄漏。

### 3.4 嵌套 filelist

- `-f` 目标必须是存在的 `.f`/filelist 文件；filelist 自身不进入 SourceSet physical manifest；
- 嵌套内容按深度优先、出现顺序展开；
- 所有 source/header 的顺序原样进入 `ordered_source_files`，不得排序；
- 同一规范化 source/header 路径重复出现，继续返回 `SOURCESET_DUPLICATE_FILE`；
- 当前递归链路中的 filelist 再次出现，返回稳定的 `SOURCESET_FILELIST_CYCLE`，不得死循环或截断成功；
- `top_closure_files`、`included_files` 和 `compile_order` 继续由现有 SourceSet/discovery 逻辑计算。

### 3.5 明确不支持的 filelist 指令

本任务不实现并且不得静默忽略：

- `+incdir+...`；
- `+define+...`；
- library mapping、blackbox、glob、工具专用选项和命令行转义；
- `-f` 与路径分成不同物理行；
- 除 `$NAME`/`${NAME}` 外的 shell 语法。

遇到上述语法返回稳定的 `SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE`，用户应通过当前 CLI 的
`--include-dir` 和 `--define` 显式提供编译上下文。是否吸收 `+incdir+`/`+define+` 另建后续任务，
不得在 T087 中顺手扩展。

## 4. 固定 compact fixture

新增目录：`tests/fixtures/t087_filelist_frontend/`

```text
tests/fixtures/t087_filelist_frontend/
├── design.f
├── nested/
│   ├── child.f
│   ├── cycle_a.f
│   └── cycle_b.f
├── rtl/
│   ├── child.sv
│   ├── ignored.sv
│   └── top.sv
├── include/
│   └── common.svh
├── duplicate.f
├── undefined_env.f
├── outside.f
└── unsupported_directive.f
```

### 4.1 正例 `design.f`

测试运行时设置 `T087_PROJ` 为 fixture 根目录的绝对路径，内容固定覆盖用户提供的四类写法：

```text
# top-level comment
$T087_PROJ/rtl/top.sv
// $T087_PROJ/rtl/ignored.sv
-f $T087_PROJ/nested/child.f
$T087_PROJ/include/common.svh
```

`child.f`：

```text
// nested comment
$T087_PROJ/rtl/child.sv
```

`top.sv` 实例化 `child` 并通过 `` `include "common.svh"`` 使用 header；`ignored.sv` 不得进入
SourceSet。正例必须证明 `$T087_PROJ` 展开、注释忽略、嵌套顺序和 `.svh` physical classification
同时成立。

另增加一个直接绝对路径正例，指向 fixture 内 `.sv`，证明 source-root 内绝对路径可归一化，而不是
只测试环境变量产生的绝对路径。

### 4.2 负例

- `duplicate.f`：通过嵌套 `-f` 使同一 `.sv` 规范化路径出现两次，期望
  `SOURCESET_DUPLICATE_FILE`；
- `cycle_a.f`/`cycle_b.f`：互相 `-f`，期望 `SOURCESET_FILELIST_CYCLE`；
- `undefined_env.f`：引用未设置的 `$T087_MISSING`，期望 `SOURCESET_ENV_UNDEFINED`；
- `outside.f`：引用 source-root 外的绝对路径或环境变量路径，期望
  `SOURCESET_PATH_OUTSIDE_ROOT`；
- `unsupported_directive.f`：包含 `+incdir+...` 或 `+define+...`，期望
  `SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE`；
- 一个 `-f` 无参数和一个 `.f` 目标不存在的负例，分别返回稳定输入错误，不得产生 partial SourceSet。

fixture 只冻结输入展开语义，不冻结 mapping 数量、随机名称、加密率或 RISC-V-Vector 数量。

## 5. 固定 API 与实现边界

### 5.1 允许修改

- `rtl_obfuscator/source_set.py`：增加 filelist tokenizer/expander 和稳定错误处理；
- `tests/test_source_set.py`：新增 T087 正负测试；
- `tests/fixtures/t087_filelist_frontend/**`：新增 compact fixture；
- `docs/tasks/T087_filelist_frontend_compatibility.md`：记录执行证据和验收结果；
- `README.md`：仅在实现验收通过后补充已支持的 filelist 语法和明确边界。

### 5.2 禁止修改

- `rtl_obfuscator/project_discovery.py`：T087 不改变 discovery/closure 算法；
- `rtl_obfuscator/source_catalog.py`、`symbol_graph.py`、`rewrite_policy.py`、`mapping_vnext.py`；
- `orchestration_vnext.py`、`rewrite_vnext.py`、`restore_vnext.py`、`formal_vnext.py`；
- 公共 CLI 的 mapping/report schema 和稳定外层错误码；
- 现有 RTL sample、历史任务单和 RISC-V-Vector 专项脚本；
- 任何真实服务器工程文件。

下游 gate 继续由既有 `rewrite_vnext` 从 `SourceSet.compile_order` 生成扁平 `design.f`；T087 不
保留原始 `$PROJ`、`-f` 或注释文本到 gate 中，也不改变现有 restore 对 canonical `design.f` 的校验。

## 6. 机器可检查行为

目标测试必须断言：

1. `design.f` 的 SourceSet `ordered_source_files` 为稳定的展开顺序；
2. 持久化 vNext/restore report 中不出现 `$T087_PROJ`、环境变量值或 filelist 绝对路径；
   `SourceSet.to_report()` 保留 T039 既有的绝对 `source_root` 字段；
3. 注释掉的 source 和注释掉的 `-f` 均不进入 SourceSet；
4. `.svh` 只进入 `included_files`，不进入 `compile_order`；
5. 绝对路径和变量展开路径在 source-root 内时得到同一个 normalized path；
6. nested filelist 的 source 顺序不被排序；
7. duplicate、cycle、undefined env、outside-root、unsupported directive 和缺失 `-f` 参数分别
   返回固定错误码；
8. 所有失败均在返回 SourceSet 前发生，不创建 gate、report 或缓存；
9. 现有 T039 测试全部保持通过；
10. `SourceSet.to_report()` 仍保持 schema v1、字段结构和 canonical JSON 行为。

## 7. 验收命令

本任务只选择 SourceSet/discovery 验收行：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_source_set -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py tests/test_source_set.py
git diff --check HEAD
```

T087 不运行 blanket discovery、RISC-V-Vector Formal、Yosys、Verible、Icarus 或真实服务器工程。
原因是本任务不产生 rewritten RTL；Formal 固定记录为：

```text
formal_verification: N/A
reason: SourceSet filelist expansion only; no rewritten RTL is produced
```

主 Agent 在验收时另做只读审查：确认公共 CLI 仍通过 `from_filelist()` 进入新 adapter，且没有
新增第二套 filelist parser。真实工程端到端加密、strict compile、restore 和 actual-gate Formal
属于后续独立适配验收，不并入 T087。

## 8. 子 Agent 执行记录模板

实现开始前必须把本任务从 `READY` 改为 `IN_PROGRESS`，并记录：

```text
status: IN_PROGRESS
starting_head:
changed_files:
baseline_commands:
baseline_results:
```

完成后只能设置 `READY_FOR_REVIEW`，并补齐：

```text
status: READY_FOR_REVIEW
starting_head:
changed_files:
commands:
results:
schema_or_behavior:
boundaries:
cleanup_candidates: none
formal_verification: N/A
review_request:
```

子 Agent 不得设置 `ACCEPTED`，不得 stage、commit、push，不得创建 T088。

## 9. 主 Agent 验收边界

主 Agent独立检查：

1. 允许文件列表和 `git diff --check HEAD`；
2. 三条固定验收命令；
3. T039 既有顺序、schema、include/header 和稳定错误行为没有回退；
4. 新 parser 只在 SourceSet 层工作，未复制 discovery、inventory 或 rewrite；
5. 外层公共 CLI、mapping、restore 和 gate `design.f` 合同没有变化。

全部通过后，主 Agent 才能将 T087 设为 `ACCEPTED`，再另行冻结真实工程适配验收任务。

## 10. 当前状态

```text
status: ACCEPTED
starting_head: 52c3090ed6deef2b2eca8a5b7a3da25c65f46980
execution_started: 2026-08-12T17:46:53+0800
changed_files: `rtl_obfuscator/source_set.py`; `tests/test_source_set.py`; `tests/fixtures/t087_filelist_frontend/**`; this task record
commands: `conda run -n rtl_obfuscation python -m unittest tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py tests/test_source_set.py`; `git diff --check HEAD`
results: unittest exit 0, 12 tests passed including the original 8 T039 SourceSet tests and T087 environment/nested/negative coverage; py_compile exit 0; `git diff --check HEAD` exit 0
schema_or_behavior: extended the existing SourceSet filelist adapter with one recursive depth-first tokenizer/expander; supports # and // full-line comments, $NAME and ${NAME}, source-root-relative and in-root absolute paths, same-line -f, stable order, duplicate detection, and active-chain cycle detection; preserves schema v1, normalized report fields, included_files, compile_order, and canonical design.f downstream semantics
boundaries: nested filelists use the frozen source-root path base and must resolve to an in-root .f or .filelist; unsupported +incdir+, +define+, library/glob/tool/shell syntax fails with SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE; undefined variables, outside-root paths, missing -f targets, and missing -f arguments fail before SourceSet creation; no CLI, discovery, inventory, mapping, rewrite, restore, Formal, README, or real-project files were changed
baseline_results: unittest exit 0, 8 tests passed before implementation; py_compile exit 0; `git diff --check HEAD` exit 0
worktree_before_task_creation: clean at 52c3090; only this task contract was untracked
real_project_files: intentionally not required for T087
cleanup_candidates: none
formal_verification: N/A
reason: SourceSet filelist expansion only; no rewritten RTL is produced
review_request: READY_FOR_REVIEW; all three contract commands passed, the allowed-file audit passed, and Main Agent independently reran the same commands and accepted the SourceSet-only diff
```

## 11. 主 Agent 独立验收

```text
acceptance_status: ACCEPTED
acceptance_head: 52c3090ed6deef2b2eca8a5b7a3da25c65f46980
independent_commands: `conda run -n rtl_obfuscation python -m unittest tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py tests/test_source_set.py`; `git diff --check HEAD`
independent_results: unittest exit 0, Ran 12 tests, OK; py_compile exit 0; git diff --check HEAD exit 0
scope_review: PASS; changed paths are limited to T087 contract, source_set.py, test_source_set.py, and t087 compact fixtures; public CLI still routes filelist input through from_filelist(); no discovery/inventory/rewrite/mapping/restore/Formal paths changed
report_review: PASS; raw `$T087_PROJ`, nested filelist names, comments, and source-root absolute filelist entries are not persisted in vNext/restore reports; the existing T039 SourceSet.to_report() absolute source_root field remains unchanged by contract
formal_verification: N/A; SourceSet filelist expansion only; no rewritten RTL is produced
decision: ACCEPTED; T087 contract behavior and independent evidence satisfy the SourceSet-only acceptance boundary
delivery: no git stage/commit/push performed in this acceptance record
```
