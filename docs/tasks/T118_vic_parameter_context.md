# T118：显式 filelist 支持只读 `.vic` 参数上下文

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 起始 HEAD：`8367e05251d4d3bc9cf3fd5cf58f5569624d4d01`（T117 已 `ACCEPTED`，工作树干净）
- 任务类型：SourceSet/filelist context adapter + compact actual-gate Formal
- 服务器输入：`dmac_parameters_64bit.vic`（178 行 compilation-unit `parameter` 声明）

## 1. 已确认的问题

真实 filelist 显式列出：

```text
dmac_parameters_64bit.vic
```

当前 SourceSet 在 PySlang 前按后缀拒绝，返回：

```text
SOURCESET_UNSUPPORTED_FILE
filelist entries must use .sv, .v, .svh, .vh, or explicit .h suffixes
```

主 Agent 已对用户提供的原文件做只读探针：文件没有 module/package，只有 compilation-unit
`parameter` 声明；PySlang parse/semantic errors 均为 0；将其置于 top 源码之前时，Icarus 与 Yosys
均能解析，并能让后续 top 引用其中的 `ADDR_BITS`。

## 2. 单一目标

让显式 filelist 接受小写 `.vic`，将其作为只读参数上下文加入 PySlang 和 canonical compile order，
使后续 `.sv/.v` source unit 能使用其中的 compilation-unit 参数；`.vic` 必须原样进入 gate/restore，
且不得成为 rename target。

## 3. 冻结语义

1. source unit 仍只有小写 `.sv/.v`。
2. `.svh/.vh` 仍是语义 header；`.h` 仍是显式 filelist-only 宏上下文。
3. 新增小写 `.vic`，仅作为显式 filelist-only 参数上下文；归入既有 context 分类，不新增 schema 字段。
4. `.vic` 进入 `included_files`、input manifest、gate、direct restore 和 canonical `design.f`；与显式
   `.h/.svh/.vh` 一样作为 context prelude 位于 source unit 前。
5. `.vic` 参与同一个 PySlang compilation，使其中的 compilation-unit 参数对后续 source unit 可见。
6. `.vic` 不进入 `ordered_source_files`，不进入 top closure，不产生 declaration/occurrence/edit，
   必须逐字节保持不变。
7. filelist 的绝对/相对路径、`$NAME`/`${NAME}`、嵌套 `-f`、重复和缺失文件错误继续复用既有规则。
8. `.VIC`、single-file `--input`、project-root 自动发现继续 fail closed。
9. T117 的 `-v PATH` 只接受 `.sv/.v`；`-v parameters.vic` 必须继续返回
   `SOURCESET_UNSUPPORTED_FILE`。
10. 公开错误信息和文档必须把 `.vic` 明确列为显式 filelist-only context，而不是普通 source suffix。

## 4. 明确不包含

- 不支持其他自定义后缀、`.VIC`、`.inc`、`.vhf` 或通配后缀；
- 不让 project-root 扫描 `.vic`，不让 single-file 接受 `.vic`；
- 不把 `.vic` 归入 rename category，不改写其中 parameter 名称；
- 不实现 `` `include`` `.vic` 的新搜索规则；本任务只支持显式 filelist entry；
- 不修改 `-v`、`-y`、`+libext+` 或 library search 语义；
- 不修改 filelist 多物理根目录策略、PySlang 配置、mapping schema、category、RenameIndex 或 Formal 强度；
- 不运行 RISC-V-Vector Formal，不使用 blanket `unittest discover`。

## 5. 固定 compact fixture 与验收结果

新增 `tests/fixtures/t118_vic_parameter_context/`：

```text
design.f
rtl/dmac_parameters_64bit.vic
rtl/top.sv
```

`.vic` 至少包含与真实文件同类的 `SIMPLE_RR`、`ADDR_BITS`、`DATA_BITS` 参数；top 必须在端口宽度和
功能表达式中使用这些参数，并包含至少一个可真实改名的内部 signal。

目标测试必须证明：

- SourceSet 的 `ordered_source_files` 只有 top，`included_files` 含 `.vic`，`compile_order` 为
  `.vic` 后接 top；PySlang parse/semantic 为 0；
- 公开 CLI actual gate 有真实 rename、strict compile 和 byte-identical restore；
- gate/restore 中 `.vic` 与 gold 逐字节相同，mapping 无任何 `.vic` range；
- canonical `design.f` 保留 `.vic`；
- `.VIC`、single-file、project-root 自动扫描、重复 `.vic`、`-v *.vic` 精确 fail closed；
- actual renamed gate 与 gold 字节不同；Formal 正例 exit 0 且 JSON `formal_equivalence=pass`；
- 固定功能负例 strict compile 通过但 Formal 非零，并含 `unproven` / `equiv_status -assert`。

## 6. 允许修改的文件

- `AGENTS.md`
- `README.md`
- `docs/formal_verification.md`
- `docs/development/project_structure.md`
- `docs/systemverilog_renaming_table.md`
- `docs/tasks/T118_vic_parameter_context.md`
- `rtl_obfuscator/rtl_files.py`
- `rtl_obfuscator/source_set.py`
- `rtl_obfuscator/project_discovery.py`（仅当既有 context plumbing 不能直接复用时）
- `tests/test_t118_vic_parameter_context.py`
- `tests/fixtures/t118_vic_parameter_context/**`

不得修改其他文件。

## 7. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t118_vic_parameter_context -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_source_set tests.test_t090_filelist_context \
  tests.test_t091_h_macro_header.HMacroHeaderTests.test_filelist_h_is_context_only_and_macro_provider_is_resolved \
  tests.test_t091_h_macro_header.HMacroHeaderTests.test_h_filelist_boundaries_fail_closed \
  tests.test_t098_authoritative_filelist tests.test_t099_filelist_compile_context \
  tests.test_t117_filelist_v_library_source.T117FilelistVLibrarySourceTests.test_v_failures_are_exact_and_duplicate_with_bare_entry -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rtl_files.py rtl_obfuscator/source_set.py rtl_obfuscator/project_discovery.py \
  tests/test_t118_vic_parameter_context.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T118_vic_parameter_context.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t118_ready_for_review=pass")'
```

## 8. Formal verification

目标测试必须从含 `.vic` 的公开 CLI 运行生成 actual gate：

```text
formal_verification: PASS
gold-filelist: tests/fixtures/t118_vic_parameter_context/design.f
gold-root: tests/fixtures/t118_vic_parameter_context
gate-filelist: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t118-formal-c7jz869i/gate/design.f
gate-root: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t118-formal-c7jz869i/gate
top: t118_top
seq: 5
positive: exit 0 and JSON formal_equivalence=pass
negative: copied actual gate, changed one ` ^ ` to ` | ` in rtl/top.sv; strict compile exit 0; Formal exit 1 with unproven/equiv_status -assert
```

## 9. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 8367e05251d4d3bc9cf3fd5cf58f5569624d4d01
started_at: 2026-08-31 10:28:04 +0800
first_command: git status --short --branch && git rev-parse HEAD
starting_worktree: only untracked docs/tasks/T118_vic_parameter_context.md (the Main Agent task contract)
allowed_files: AGENTS.md; README.md; docs/formal_verification.md; docs/development/project_structure.md; docs/systemverilog_renaming_table.md; docs/tasks/T118_vic_parameter_context.md; rtl_obfuscator/rtl_files.py; rtl_obfuscator/source_set.py; rtl_obfuscator/project_discovery.py only if needed; tests/test_t118_vic_parameter_context.py; tests/fixtures/t118_vic_parameter_context/**
changed_files: AGENTS.md; README.md; docs/formal_verification.md; docs/development/project_structure.md; docs/systemverilog_renaming_table.md; docs/tasks/T118_vic_parameter_context.md; rtl_obfuscator/rtl_files.py; rtl_obfuscator/source_set.py; rtl_obfuscator/project_discovery.py; tests/test_t118_vic_parameter_context.py; tests/fixtures/t118_vic_parameter_context/design.f; tests/fixtures/t118_vic_parameter_context/rtl/dmac_parameters_64bit.vic; tests/fixtures/t118_vic_parameter_context/rtl/top.sv
commands: baseline target unittest (expected missing module); then the five exact Section 7 commands, with the status guard run after this record update
results: target 4/4 PASS; related regression 28/28 PASS; py_compile exit 0; git diff --check HEAD exit 0; public CLI rename>0, modified_tokens>0, strict_compile_passed=true, restored_byte_identical=true; canonical design.f is `.vic` then top; gate/restore `.vic` byte-identical; mapping has no `.vic` declaration or occurrence range
schema_or_behavior: no schema change; bare explicit filelist-only lower-case `.vic` joins the existing context classification and canonical context prelude, while ordered_source_files/top closure/rename targets remain `.sv/.v` only
boundaries: `.VIC`, single-file, project-root discovery, duplicate `.vic`, missing `.vic`, `-v *.vic`, and implicit `` `include`` `.vic` fail closed; no other suffix, include rule, or library search was added
cleanup_candidates: none
formal_verification: PASS; gold-filelist=tests/fixtures/t118_vic_parameter_context/design.f; gold-root=tests/fixtures/t118_vic_parameter_context; gate-filelist=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t118-formal-c7jz869i/gate/design.f; gate-root=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t118-formal-c7jz869i/gate; top=t118_top; seq=5; positive exit 0 and JSON formal_equivalence=pass; negative actual-gate copy changed one ` ^ ` to ` | ` in rtl/top.sv, strict compile exit 0, Formal exit 1 with unproven/equiv_status -assert
uncovered_boundaries: none within the frozen T118 scope
review_request: Main Agent please independently rerun all five Section 7 commands and inspect the actual-gate Formal evidence; do not set ACCEPTED unless each result remains exact
```

## 10. 主 Agent 验收

```text
main_result: ACCEPTED
reviewed_at: 2026-08-31
reviewed_head: 8367e05251d4d3bc9cf3fd5cf58f5569624d4d01
scope_review: PASS; all 13 changed/new paths are inside the Section 6 allowlist
target_tests: 4/4 PASS
related_regression: 28/28 PASS
py_compile: exit 0
diff_check: exit 0
ready_for_review_guard: t118_ready_for_review=pass (run before this ACCEPTED transition)
formal_positive: exit 0; JSON formal_equivalence=pass; actual gate=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t118-formal-kkyo2za2/gate
formal_negative: copied actual gate; xor-to-or mutation; strict compile exit 0; Formal exit 1 with unproven/equiv_status -assert
boundary_review: PASS; .vic remains bare explicit-filelist-only context and is rejected by --input, project-root discovery, implicit `include`, -v, and upper-case .VIC
```
