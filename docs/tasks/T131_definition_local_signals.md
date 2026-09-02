# T131：无层级展开的 module-definition-local signals 快速路径

- 状态：`ACCEPTED`
- 负责人：子 Agent（实现与自测）/ 主 Agent（合同与验收）
- 起始分支：`delivery/fast-local-signals`
- 起始提交：`e870f7a2e3a73a4a4ff1c420f55d52e5ff5d3ddb`

## 1. 单一目标

保持现有公开命令、SourceSet、MappingVNext、rewrite、restore 和原子失败合同不变，把 T130 的
filelist + rewrite-root + signals 快速 mapping 从“查找已展开的 InstanceBodySymbol”替换为一条统一的
module-definition-local CST 规则。完整 filelist 只提供有序预处理、宏、include 和语法上下文；mapping
阶段不得创建 PySlang `Compilation`，不得选择 top，不得读取 `topInstances`，不得遍历 module 实例或
依赖闭包。rewrite-root 内已经解析成功但当前配置没有 semantic body 的 module 必须与其他目标 module
使用完全相同的候选、保留和改写算法。

## 2. 固定输入

主 Agent 冻结以下只读输入，子 Agent 不得修改：

```text
tests/fixtures/t131_definition_local_signals/design.f
tests/fixtures/t131_definition_local_signals/formal.f
tests/fixtures/t131_definition_local_signals/external/top.sv
tests/fixtures/t131_definition_local_signals/owned/unused_a.sv
tests/fixtures/t131_definition_local_signals/owned/unused_b.sv
tests/fixtures/t131_definition_local_signals/owned/shadowed.sv
tests/fixtures/t130_fast_local_signals/**
```

T131 的 external top 只在常量假 generate 中引用三个 owned module，固定复现“定义存在、实例计数为
0、没有 semantic body”。公开输入保持：

```sh
python rtl_encrypt.py \
  --filelist tests/fixtures/t131_definition_local_signals/design.f \
  --rewrite-root tests/fixtures/t131_definition_local_signals/owned \
  --category signals \
  --output-dir <new-output>
```

## 3. 冻结设计与行为

### 3.1 唯一工作流

1. 按 SourceSet 的原始 compile order、include dirs 和 defines 对完整 filelist 做一次 PySlang
   preprocess/parse，保留 `SourceManager`、单一 CST 和现有 vendor 精确诊断分类；mapping 阶段不得调用
   `Compilation.getRoot()` 或收集 semantic diagnostics。
2. 只枚举 rewrite-root 显式 source unit 中的直接 `ModuleDeclaration`。每个 owner 继续由 module 名及
   物理 declaration range 标识，不依赖实例路径。
3. 候选只来自 `ModuleDeclaration.members` 的直接 `DataDeclaration` / `NetDeclaration` declarator；支持
   T130 已覆盖的 module 直接 `logic` 与 `wire`，排除 ANSI/non-ANSI port、parameter/localparam、typedef、
   interface/struct/union/class 类型对象、genvar，以及 function/task/block/generate 内声明。
4. 对每个候选，在该物理 module span 的 CST 中枚举同拼写 identifier。只有 declaration token 与每个
   occurrence 都能由明确的 value-expression 语法位置和唯一物理字节范围证明属于该直接信号时才改名。
5. 同一 module 内出现同名嵌套声明、成员/层次选择、named port/parameter/argument 标签、类型位置、宏
   来源、escaped identifier、无法定位 token 或任何未列入安全 value-reference allowlist 的拼写时，
   只把对应 module signal 标记为 `preserve`，固定 reason 为 `syntax_local_ambiguous`；不得猜测、替换或
   让整个作业因这种对象级歧义失败。
6. 不同 module 的同名信号按物理 owner 独立建 record，并继续使用全 mapping unavailable-name 集合产生
   不同新名。
7. rewrite 后仍用完整 gate filelist 做一次现有 strict PySlang validation；decrypt byte identity、范围
   审计、事务写出和失败清理不变。

### 3.2 结构禁令

- 所有目标 module 必须走同一 CST 算法；禁止“已展开 module 走 semantic、未展开 module 走 fallback”。
- 禁止把目标 module 逐个或批量加入 `topModules`。
- 禁止读取 `root.topInstances`、遍历 `InstanceSymbol` / `InstanceBodySymbol`、计算依赖闭包或实例路径。
- 禁止复制通用 RenameIndex collector、字符串全局替换、按 fixture/module 名分支或新增兼容层。
- 物理拼写扫描只可作为 completeness/preserve 证据，不能单独授权一个 occurrence 进入 rewrite edits。
- mapping 阶段不得按目标文件重复解析完整 filelist；完整 source parse 恰好一次，gate validation 另一次。

## 4. 预期机器可读结果

公开 CLI 保持 `format=rtl-obfuscation.cli-vnext`、`schema_version=2`、退出码 0；报告满足：

```text
summary.strict_compile_passed   = true
summary.restored_byte_identical = true
summary.unsupported             = 0
modified files                  = owned/*.sv only
external/top.sv                 = byte-identical
```

T131 mapping 精确包含四个 record：

```text
t131_unused_a.state       action=rename
t131_unused_a.next_state  action=rename
t131_unused_b.state       action=rename
t131_shadowed.state       action=preserve reason=syntax_local_ambiguous
```

两个被改名的 `state` 必须具有不同 `symbol_id`、不同 `semantic_owner` 和不同 `renamed_name`。ports、函数
参数 `value` 和函数局部 `state` 不得产生独立 signal record。T130 的公开快速路径、strict gate、decrypt、
同名跨 module 隔离及 compact Formal 行为必须继续通过；T130 中有同名函数局部声明的 module 直接 signal
允许从 rename 收紧为 `syntax_local_ambiguous` preserve，其他无歧义的直接 `logic/wire` 仍必须改名。

## 5. 不包含

- 不支持 ports/interface/struct/all、带 `--top`、带 `--encryption-rate`、project-root 或 single-file 的
  新快速模式；现有分派不变。
- 不实现 SystemVerilog 通用 lexical binder，不追求歧义对象的最大覆盖率。
- 不处理字符串形式 UVM/DPI/PLI 路径，不修改宏定义或 rewrite-root 外文件。
- 不修改 CLI 参数、SourceSet schema、MappingVNext schema、report schema 或 restore schema。
- 不增加 analysis-root、缓存、并行、compiled library、39 个模块特判或按 module 补充 elaborate。
- 不删除或放宽历史测试，不运行 RISC-V-Vector Formal，不运行真实 AIClusterWrapper。

## 6. 允许修改文件

子 Agent 只能修改：

```text
docs/tasks/T131_definition_local_signals.md
rtl_obfuscator/fast_local_signals.py
rtl_obfuscator/project_discovery.py
tests/test_t131_definition_local_signals.py
tests/test_t130_fast_local_signals.py
README.md
docs/systemverilog_renaming_table.md
docs/development/project_structure.md
```

第 2 节 fixture 为主 Agent 冻结输入。需要修改其他产品文件、fixture、schema 或历史任务时，先记录偏差并
停止，不得扩大范围。

## 7. Baseline

子 Agent 在编辑实现文件前运行；当前预期为失败，首个错误包含
`target module has no semantic body`：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t131_definition_local_signals.T131DefinitionLocalSignalsTests.test_unelaborated_modules_use_one_definition_local_policy -v
```

## 8. 固定验收命令

本任务选择 rewrite/mapping 验收行，固定五条：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t131_definition_local_signals \
  tests.test_t130_fast_local_signals -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t098_authoritative_filelist \
  tests.test_t125_single_view_rewrite_root_catalog -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/fast_local_signals.py \
  rtl_obfuscator/project_discovery.py \
  tests/test_t131_definition_local_signals.py \
  tests/test_t130_fast_local_signals.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T131_definition_local_signals.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t131_ready_for_review=pass")'
```

第一条必须内部完成 T131/T130 公共 CLI、外部文件 byte identity、decrypt byte identity、mapping 阶段
`Compilation` 禁用 guard，以及 actual rewritten gate 的 compact Formal 正例和固定功能负例。T131 Formal：

```text
gold-filelist = tests/fixtures/t131_definition_local_signals/formal.f
gold-root     = tests/fixtures/t131_definition_local_signals
gate-filelist = <actual gate>/formal.f
gate-root     = <actual gate>
top           = t131_unused_a
seq           = 5
positive      = exit 0 and JSON formal_equivalence=pass
negative      = actual gate 中唯一 ` ^ ` 改为 ` | `，exit nonzero，含 unproven 与 equiv_status -assert
```

## 9. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: e870f7a2e3a73a4a4ff1c420f55d52e5ff5d3ddb
changed_files: "docs/tasks/T131_definition_local_signals.md; rtl_obfuscator/fast_local_signals.py; rtl_obfuscator/project_discovery.py; tests/test_t131_definition_local_signals.py; tests/test_t130_fast_local_signals.py; README.md; docs/systemverilog_renaming_table.md; docs/development/project_structure.md; frozen T131 fixture unchanged"
commands: "start 2026-09-02 16:57:23 +0800; baseline; correction after CHANGES_REQUESTED; conda run -n rtl_obfuscation python -m unittest tests.test_t131_definition_local_signals tests.test_t130_fast_local_signals -v; conda run -n rtl_obfuscation python -m unittest tests.test_t098_authoritative_filelist tests.test_t125_single_view_rewrite_root_catalog -v; conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/fast_local_signals.py rtl_obfuscator/project_discovery.py tests/test_t131_definition_local_signals.py tests/test_t130_fast_local_signals.py; git diff --check HEAD; actual CLI gate /private/tmp/t131-final.bRXRty/gate; Formal positive and fixed negative"
results: "baseline failed as expected with target module has no semantic body; corrected T131/T130 14/14; corrected T098/T125 11/11 including existing T125 Formal positive/negative; py_compile pass; diff-check pass; actual CLI schema 2, strict_compile_passed/restored_byte_identical true, 4 records (3 rename, 1 preserve), external/top.sv unchanged; direct mapping Compilation guard passes and no hierarchy helper is retained; each of 3 target modules builds exactly one inventory; ambiguity matrix is nonfatal with 3 object-level preserves and ordinary function value rename"
schema_or_behavior: "parse_pyslang_source_set is called directly by fast mapping; PySlangSyntaxView has no root field and SourceCatalog.catalog_root is None. One shared SourceManager/Bag/CST parse primitive and one shared syntax/vendor diagnostic classifier serve syntax-only and semantic compile paths. Per-module inventory groups identifier tokens/declarators by spelling, preclassifies ambiguity and uses a physical path/bytes cache; each signal reads only its same-name bucket. Fast dispatch remains filelist + rewrite-roots + signals-only + no top/rate. Mapping/CLI/SourceSet/rewrite/restore schema remains v2/unchanged; gate uses the existing full strict compile."
boundaries: "Conservative definition-local CST scope intentionally covers direct logic/wire declarations only; ports, parameters, typedef/aggregate/interface, subroutine/block/generate locals and rewrite-root external files are not candidates. Contract typo for the T098 module was corrected to tests.test_t098_authoritative_filelist and that row was rerun."
cleanup_candidates: "none"
formal_verification: "PASS; gold tests/fixtures/t131_definition_local_signals/formal.f; gate /private/tmp/t131-final.bRXRty/gate/formal.f; top t131_unused_a; seq 5; command conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t131_definition_local_signals/formal.f --gold-root tests/fixtures/t131_definition_local_signals --gate-filelist /private/tmp/t131-final.bRXRty/gate/formal.f --gate-root /private/tmp/t131-final.bRXRty/gate --top t131_unused_a --seq 5; positive exit 0 JSON formal_equivalence=pass; fixed unused_a.sv ^ -> | negative gate /private/tmp/t131-final-negative.nkDqOf exit 1 containing unproven and equiv_status -assert"
review_request: "READY_FOR_REVIEW; all corrected acceptance rows pass, no commit/push; main Agent to independently rerun the exact rows, review allowed-file diff and set ACCEPTED only after review."

correction_2026-09-02: "主 Agent 审查为 CHANGES_REQUESTED。按同一合同退回 IN_PROGRESS：删除 PySlangSyntaxView.root 与 fast _compile_view 兼容层；mapping 直接使用 parse-only API 且 SourceCatalog.catalog_root=None；共享 syntax/vendor 诊断分类；建立每 module 一次的 CST 索引及 source bytes cache，补充歧义矩阵与 inventory 计数 guard。"
```

## 10. 偏差或阻塞

```text
acceptance_command_note: "主 Agent 已将第 8 节第二条的模块名笔误从不存在的 tests.test_t098_authoritative_filelist_pyslang 勘误为仓库实际模块 tests.test_t098_authoritative_filelist；测试范围与行为未改变。"
```

## 11. 主 Agent 验收记录

```text
status: ACCEPTED
reviewed_head: e870f7a2e3a73a4a4ff1c420f55d52e5ff5d3ddb + T131 working tree
acceptance: "主 Agent 独立执行第 8 节五条固定命令：T131/T130 14/14；T098/T125 11/11；py_compile pass；git diff --check HEAD pass；READY_FOR_REVIEW guard pass。"
code_review: "确认 fast mapping 直接调用 parse_pyslang_source_set；映射阶段不构造 Compilation、不读取 getRoot/topInstances、不选择或补充 top、不遍历实例/依赖层级。rewrite-root 内每个 module definition 只建立一次紧凑 CST inventory，identifier 按 spelling 分桶，每个 signal 只检查同名桶；物理路径和 source bytes 有任务级缓存。候选严格限于 module 直接 logic/wire，非唯一 IdentifierName、宏、成员/层次、named label、类型位置、escaped identifier 和同名嵌套声明均对象级 preserve。公开 CLI、SourceSet、MappingVNext、rewrite/restore schema 未改变。"
blocking_findings: "none；首轮审查发现的 semantic compatibility layer 与逐 signal 全模块扫描已经在同一 T131 合同内修正。最终额外核验同名 module 实例类型的 CST 不是 value-reference，不能授权 signal edit。"
resolution: "ACCEPTED；实现、文档和测试均落在合同允许文件内，冻结 fixture 未被子 Agent 修改。"
formal_verification: "PASS；主 Agent 的固定第一条验收命令独立触发实际 rewritten gate Formal：gold tests/fixtures/t131_definition_local_signals/formal.f，gate 为测试生成的实际加密输出 formal.f，top t131_unused_a，seq 5；正例 exit 0 且 formal_equivalence=pass；固定 ^ -> | 负例 exit nonzero，含 unproven 与 equiv_status -assert。T130 与 T125 的实际 gate Formal 回归同时通过。"
next_step: "按 Git 流程提交并推送 delivery/fast-local-signals；不在 T131 内增加后续优化。"
```
