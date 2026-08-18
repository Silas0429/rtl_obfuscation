# T091：filelist `.h` 宏头文件适配

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：GPT-5.6 Luna Extra high 子 Agent
- 前置任务：T088 `.v/.vh` 输入支持、T090 filelist 上下文指令支持，当前基线 `ea044d3`
- 任务类型：SourceSet/filelist adapter migration + compact end-to-end gate/Formal
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：必须使用本任务 compact `.h` 宏头文件 fixture 完成 actual renamed gate 正例和固定功能负例

## 1. 单一目标

让显式 filelist 支持服务器工程中的 `.h` 宏头文件作为只读编译上下文，覆盖以下形状：

```text
$PROJ/common/src/StLib/common/stl_gmacro.h
$PROJ/common/src/StLib/impl_template/tsmc4/stl_gsetting_base.h
$PROJ/common/src/StLib/impl_template/tsmc4/stl_gsetting_freq.h
$PROJ/common/src/StLib/impl_template/tsmc4/stl_gsetting_report.h
```

`.h` 文件必须：

- 可以作为 filelist 的显式 entry，也可以通过已支持的嵌套 `-f` 出现；
- 可以作为 source 的 `` `include `` provider，并参与宏 provider 分析；
- 进入 `SourceSet.included_files`、input manifest、gate 和 direct restore；
- 保持原始字节，不产生宏定义或宏引用 rename edit；
- 不进入 `compile_order`，不成为单独的 source unit。

实现继续使用当前 PySlang SystemVerilog semantic frontend；不新增 legacy Verilog parser，不为宏
建立第二套加密流水线。

## 2. 冻结输入和候选范围

### 2.1 后缀分类

- source unit：`.sv`、`.v`；
- 可承载语义 header：`.svh`、`.vh`，保持 T088 行为；
- context-only macro header：`.h`；
- `.H`、`.hh`、`.hpp`、`.txt` 和其它后缀继续 fail-closed。

### 2.2 filelist-only 规则

- `.h` 只在显式 filelist模式中接受；必须被 filelist 直接列出或由嵌套 filelist 列出；
- `.h` 不被 single-file 作为 `--input` 接受；
- `.h` 不被 project-root 自动扫描；project-root 和 single-file 的既有 `.sv/.v/.svh/.vh`
  行为不变；
- filelist 的相对路径、绝对路径、`$NAME`/`${NAME}`、`-f`、`+incdir+` 和重复/cycle/error
  语义继续沿用 T087/T090；
- filelist 模式只把显式列出的 `.h` 加入候选 macro provider 集合，不把 source-root 下所有 `.h`
  自动加入候选集合。这样宽 source-root 不会引入无关 provider 并制造伪造的 multiple-provider 错误；
- `.h` 的 include 必须能在显式 filelist 候选或已有 include 目录中唯一解析；缺失、越根和歧义继续
  返回稳定失败，不得静默跳过。

### 2.3 加密和物理发布边界

- `.h` 的宏定义、宏引用和宏生成 token 不属于任何 rename category；
- `.h` 如果只含宏定义，不得在 mapping records 中产生 rename edit；
- `.h` 作为物理文件复制到 gate，并在 direct restore 中逐字节恢复；
- source 中普通 `.sv/.v` signal 仍必须能够产生真实 rename、严格编译和 restore；
- `.h` 中若出现当前语义流水线无法安全归属的普通 declaration/reference，必须保守失败或 preserve，
  不得借本任务扩大宏头文件的 rename 范围。

## 3. 固定 compact fixture

新增 `tests/fixtures/t091_h_macro_header/`：

```text
tests/fixtures/t091_h_macro_header/
├── design.f
└── rtl/
    ├── stl_gmacro.h
    └── top.sv
```

`design.f` 必须显式列出 `rtl/stl_gmacro.h` 和 `rtl/top.sv`；`top.sv` 使用相对
`` `include "stl_gmacro.h" ``，并使用 header 提供的一个宏，同时声明至少一个普通 signal，top
固定为 `t091_top`。fixture 必须是可综合的 SystemVerilog 语义输入。

测试必须覆盖：

1. SourceSet 接受 `.h`，将其放入 `included_files` 而不是 `compile_order`；
2. `.h` 宏 provider 能解决 source 中的宏引用；
3. public filelist encryption 的 `signals` 产生 `rename > 0`，`.h` 无 rename record；
4. gate 中 `.h` 与 source 均存在，严格编译和内部 restore 通过，`.h` 字节不变；
5. direct decrypt 后 source 与 `.h` 均 byte-identical；
6. actual-gate Formal 正例 JSON 为 `formal_equivalence=pass`；
7. 将 gate 中一个普通 signal RHS 做固定 `^ -> |` 功能破坏，strict compile 仍可通过但 Formal 必须
   非零失败并保留 `equiv_status -assert` 证据；
8. `.h` 作为 `--input`、未显式列出的 `.h` include、`.H` 和重复 `.h` entry 继续 fail-closed。

## 4. 明确不包含

- 不支持 `.h` 作为独立 source unit；
- 不支持 project-root 自动发现 `.h`；
- 不支持宏重命名、宏展开文本替换、shell、library map、glob 或其它 vendor filelist 语法；
- 不修改 SymbolGraph owner/category、MappingVNext schema、rate/metrics 方程、restore API 或
  Formal 证明强度；
- 不修改服务器工程和现有 T087/T088/T090 fixture；不删除旧测试；
- 普通实现、测试、文档和 Formal 失败必须在本合同内修正，不得拆成下一任务；只有需要允许文件外
  改动或改变上述边界时才记录偏差并停止等待主 Agent。

## 5. 允许修改

```text
AGENTS.md
README.md
docs/systemverilog_renaming_table.md
docs/development/project_structure.md
docs/development/future_work.md
docs/tasks/T091_h_macro_header_support.md
rtl_obfuscator/rtl_files.py
rtl_obfuscator/source_set.py
rtl_obfuscator/project_discovery.py
tests/test_t091_h_macro_header.py
tests/fixtures/t091_h_macro_header/**
```

允许列表外不得修改；子 Agent 不得 commit 或 push。

## 6. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t091_h_macro_header tests.test_t088_verilog_suffix tests.test_source_set -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rtl_files.py rtl_obfuscator/source_set.py \
  rtl_obfuscator/project_discovery.py tests/test_t091_h_macro_header.py \
  tests/test_t088_verilog_suffix.py tests/test_source_set.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c \
  'from pathlib import Path; text=Path("docs/tasks/T091_h_macro_header_support.md").read_text(encoding="utf-8"); assert "- 状态：`READY_FOR_REVIEW`" in text; print("READY_FOR_REVIEW guard=pass")'
```

The target unittest owns the compact actual-gate Formal positive/negative calls and must record the
exact gold, gate, top, command, exit code, and JSON/failure evidence in the execution record.

## 7. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: ea044d3
changed_files:
  - AGENTS.md
  - README.md
  - docs/systemverilog_renaming_table.md
  - docs/development/project_structure.md
  - docs/development/future_work.md
  - docs/tasks/T091_h_macro_header_support.md
  - rtl_obfuscator/rtl_files.py
  - rtl_obfuscator/source_set.py
  - rtl_obfuscator/project_discovery.py
  - tests/test_t091_h_macro_header.py
  - tests/fixtures/t091_h_macro_header/design.f
  - tests/fixtures/t091_h_macro_header/rtl/stl_gmacro.h
  - tests/fixtures/t091_h_macro_header/rtl/top.sv
commands:
  - baseline: conda run -n rtl_obfuscation python -m unittest tests.test_t091_h_macro_header tests.test_t088_verilog_suffix tests.test_source_set -v
  - target: conda run -n rtl_obfuscation python -m unittest tests.test_t091_h_macro_header tests.test_t088_verilog_suffix tests.test_source_set -v
  - syntax: conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rtl_files.py rtl_obfuscator/source_set.py rtl_obfuscator/project_discovery.py tests/test_t091_h_macro_header.py tests/test_t088_verilog_suffix.py tests/test_source_set.py
  - diff: git diff --check HEAD
  - guard: conda run -n rtl_obfuscation python -c 'from pathlib import Path; text=Path("docs/tasks/T091_h_macro_header_support.md").read_text(encoding="utf-8"); assert "- 状态：`READY_FOR_REVIEW`" in text; print("READY_FOR_REVIEW guard=pass")'
  - formal_positive: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t091_h_macro_header/design.f --gold-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t091_h_macro_header --gate-filelist /tmp/t091-formal-evidence.WbK1hR/gate/design.f --gate-root /tmp/t091-formal-evidence.WbK1hR/gate --top t091_top --seq 5
  - formal_negative_strict: conda run -n rtl_obfuscation iverilog -g2012 -t null -s t091_top -I /tmp/t091-formal-evidence.WbK1hR/negative/rtl /tmp/t091-formal-evidence.WbK1hR/negative/rtl/top.sv
  - formal_negative: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t091_h_macro_header/design.f --gold-root /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t091_h_macro_header --gate-filelist /tmp/t091-formal-evidence.WbK1hR/negative/design.f --gate-root /tmp/t091-formal-evidence.WbK1hR/negative --top t091_top --seq 5
results:
  - baseline: existing 19 tests passed; expected T091 module import failed because it did not exist yet
  - target: 23 tests passed
  - syntax: exit 0
  - diff: exit 0
  - guard: exit 0, READY_FOR_REVIEW guard=pass
  - public compact encryption: exit 0; action_counts rename=1, preserve=3, unsupported=0; strict_compile_passed=true; restored_byte_identical=true
  - h behavior: explicit .h is in included_files and physical gate/restore; it is absent from compile_order and has no mapping declaration/occurrence
  - formal_positive: exit 0; {"formal_equivalence":"pass","gate":"/tmp/t091-formal-evidence.WbK1hR/gate","gold":"/Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t091_h_macro_header","seq":5,"top":"t091_top"}
  - formal_negative_strict: exit 0
  - formal_negative: exit 1; Yosys reported 1 unproven $equiv cell and `equiv_status -assert`
  - documentation: AGENTS.md, README.md, project structure, future-work, and renaming table describe explicit filelist-only `.h` context headers
schema_or_behavior: explicit filelist-only .h context headers are accepted as macro/include providers, preserved byte-for-byte in gate and direct restore, excluded from compile_order and rename edits; single-file, project-root auto-discovery, uppercase .H, missing explicit .h, and duplicate .h remain fail-closed
boundaries: no project-root automatic .h scan; no .h single-file source mode; no macro rename or macro text rewrite; no fallback, schema, SymbolGraph, Mapping, restore, or Formal strength changes
cleanup_candidates: none
formal_verification: PASS
gold: /Users/lufengchi/Desktop/workspace/rtl_obfuscation/tests/fixtures/t091_h_macro_header/design.f
gate: /tmp/t091-formal-evidence.WbK1hR/gate/design.f
top: t091_top
command: see formal_positive above; functional negative uses /tmp/t091-formal-evidence.WbK1hR/negative/design.f
exit_code: positive 0; negative 1
result: positive JSON formal_equivalence=pass; negative contains unproven and equiv_status -assert
review_request: implementation and self-test complete; ready for Main Agent independent acceptance; no commit or push performed
```

## 8. 主 Agent 验收

```text
acceptance_status: ACCEPTED
acceptance_head: ea044d3
allowed_files: PASS; only the contract-allowed AGENTS/docs, rtl_files.py, source_set.py, project_discovery.py, T091 tests, and T091 fixture changed
independent_commands: `conda run -n rtl_obfuscation python -m unittest tests.test_t091_h_macro_header tests.test_t088_verilog_suffix tests.test_source_set -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rtl_files.py rtl_obfuscator/source_set.py rtl_obfuscator/project_discovery.py tests/test_t091_h_macro_header.py tests/test_t088_verilog_suffix.py tests/test_source_set.py`; `git diff --check HEAD`; exact READY_FOR_REVIEW guard
independent_results: unittest exit 0, Ran 23 tests, OK; py_compile exit 0; diff check exit 0; READY_FOR_REVIEW guard exit 0; T091 test independently proved Formal positive exit 0 with formal_equivalence=pass and fixed negative exit 1 with unproven/equiv_status -assert
formal_verification: PASS; compact actual renamed gate used the T091 `.h` provider fixture, top t091_top, and fixed functional negative
decision: ACCEPTED
```
