# T120：显式 `.vic` 上下文允许被源码 include

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 起始 HEAD：`98cd9662d2889574f85aa4d4fa37a396a8ad48d3`（T119 已 `ACCEPTED`，工作树干净）
- 任务类型：SourceSet include closure + combined public adapter + compact actual-gate Formal
- 服务器证据：T118 后显式 `.vic` 已通过 suffix/filelist 读取，但源码对同一文件的 `` `include`` 触发
  `SOURCESET_UNSUPPORTED_FILE: .vic parameter context must be listed explicitly in the filelist`

## 1. 仓库复审与根因

主 Agent 在冻结本任务前重新审查了 T118/T119 合同、`_read_filelist`、
`_discover_explicit_include_headers`、authoritative PySlang compilation、canonical compile order、gate/restore
以及相关测试。确认：

1. T118 正确支持显式裸 `.vic` context prelude，也正确拒绝仅靠 include 隐式发现的 `.vic`。
2. 当前 include closure 遇到任何 `.vic` 候选都会立即拒绝，没有检查候选的规范化完整路径是否已经在
   `explicit_header_files` 中；所以错误提示要求的条件即使已满足仍会失败。
3. 不能把 `.vic` 加入全局 `INCLUDE_CONTEXT_SUFFIXES`：那会错误允许未列入 filelist 的隐式 `.vic`。
4. 主 Agent 探针确认：显式 `.vic` 加 module-scope include 在 PySlang、Icarus、Yosys 均可编译；
   compilation-unit include 在 PySlang/Yosys 可编译，但 Icarus 会报告同一 `$unit` parameter 重复。
   产品仍以冻结的 SystemVerilog/PySlang semantic mode 为准，不新增 Icarus 方言分支。
5. 为避免再次遗漏组合路径，T120 的 actual gate 必须同时覆盖：显式 `.vic` + `` `include``、T117
   `-v` source，以及 T119 `source_root == /` 输出。

## 2. 单一目标

在 authoritative filelist 中，允许源码或显式 header/context 通过 `` `include`` 引用**已经作为裸条目
显式列出的同一规范化小写 `.vic` 路径**；该 `.vic` 仍只作为一个只读物理 context/prelude 保留，
未显式列出的 `.vic` 继续 fail closed。

## 3. 冻结语义

1. `.vic` 仍必须先以裸路径出现在有效 filelist（可来自嵌套 `-f`，可使用既有环境变量和绝对/相对路径
   规则）；`-v *.vic` 仍非法。
2. include candidate 必须先经既有 root/path normalization；只有规范化完整路径存在于显式
   header/context 集合时才允许。同 basename、不同目录的 `.vic` 不得误匹配。
3. 显式 `.vic` 可由 source 直接 include，也可经显式/已发现的 `.h/.svh/.vh` include closure 间接引用；
   本地相对查找和既有 `+incdir+` 查找都必须使用同一精确路径规则。
4. 未显式列出的 `.vic`，无论本地可找到还是由 `+incdir+` 找到，继续返回
   `SOURCESET_UNSUPPORTED_FILE` 和现有稳定 message/path。
5. 不把 `.vic` 加入 `INCLUDE_CONTEXT_SUFFIXES`，不改变 project-root/single-file include discovery，
   不新增 include 搜索、优先级或歧义规则。
6. 允许的 `.vic` 在 `included_files` 和 canonical `compile_order` 中各只出现一次，仍位于 source unit
   前；source 中原始 `` `include`` 文本不删除、不改写。
7. `.vic` 继续进入 input/gate/restored manifest 和 canonical `design.f`，逐字节不变；不进入
   `ordered_source_files`、top closure、rename target、declaration/occurrence/edit range。
8. 不压制 PySlang parse/semantic diagnostic，不因 Icarus 对 compilation-unit 重复 parameter 的不同处理
   新增模式分支；module-scope include 作为 public gate/Formal 固定正例。
9. T117 `-v`、T119 global-root output、schema 2、portable report、atomic publish/rollback、direct restore 和
   Formal 强度全部保持不变。

## 4. 明确不包含

- 不允许 include-only `.vic`，不支持 `.VIC`、其他自定义后缀或通配后缀；
- 不修改 `.vic` 内容、parameter 名称或 include directive；
- 不改变 context prelude、compilation-unit 或 filelist duplicate 语义；
- 不修改 `rtl_files.py` 的 suffix 集合，不修改 project-root discovery；
- 不改变 include 的 local/`+incdir+` 优先级、absolute include 或多候选歧义行为；
- 不修改 mapping/orchestration/report schema、category、RenameIndex 或 output 策略；
- 不运行 RISC-V-Vector Formal，不使用 blanket `unittest discover`。

## 5. 固定 fixture、边界矩阵与机器结果

新增 `tests/fixtures/t120_explicit_vic_include/rtl/child.v`。目标测试在系统临时目录创建
`dmac_parameters_64bit.vic`、module-scope include 的 `top.sv` 和绝对路径 filelist：

```text
<temporary>/dmac_parameters_64bit.vic
-v <repository>/tests/fixtures/t120_explicit_vic_include/rtl/child.v
<temporary>/top.sv
```

committed child 与临时文件使 `infer_filelist_root(...) == Path("/")`；top 必须 include 同目录的显式
`.vic`、使用其中 parameter、实例化 `-v` child，并含实际可改名 signal。

目标测试至少分四组证明：

1. **精确显式匹配正例**：module-scope 和 compilation-unit direct include 均通过 SourceSet/PySlang；
   `+incdir+`、嵌套 `-f`/环境变量、经 `.h` 间接 include 均能匹配同一显式规范化路径；
   `included_files`/`compile_order` 不重复。
2. **fail-closed 负例**：include-only local `.vic`、include-only `+incdir+` `.vic`、只显式列出另一个目录
   的同名 `.vic` 均精确失败；T118 的 `.VIC`、duplicate、`-v *.vic`、single-file、project-root 边界不变。
3. **组合公开 gate/restore**：`source_root=/`、`-v child.v`、显式 `.vic` + include 同时存在时 public CLI
   exit 0；schema 2、rename/modified token 大于 0、strict compile 与 restored-byte-identical 为 true；
   canonical `design.f` 为 context prelude + 两个 source；gate/direct restore 三个物理输入逐字节审计；
   `.vic` 无任何 mapping range，实际 gate 与 gold 不同。
4. **Formal 正负例**：使用 root-relative bare gold filelist 与 actual gate `design.f`；正例 exit 0 且 JSON
   `formal_equivalence=pass`；复制 actual gate 后把一个 XOR 改为 OR，Icarus strict compile exit 0，Formal
   非零并含 `unproven` / `equiv_status -assert`。

实现前必须用目标测试确认当前 HEAD 至少在“显式同一路径 `.vic` + include”上返回
`SOURCESET_UNSUPPORTED_FILE`。

## 6. 允许修改的文件

- `AGENTS.md`
- `README.md`
- `docs/formal_verification.md`
- `docs/development/project_structure.md`
- `docs/systemverilog_renaming_table.md`
- `docs/tasks/T120_explicit_vic_include_reference.md`
- `rtl_obfuscator/source_set.py`
- `tests/test_t120_explicit_vic_include_reference.py`
- `tests/fixtures/t120_explicit_vic_include/**`

不得修改其他文件；尤其不得修改 `rtl_obfuscator/rtl_files.py`、`project_discovery.py`、rewrite/mapping/
orchestration 或历史任务/测试。

## 7. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t120_explicit_vic_include_reference -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_source_set tests.test_t090_filelist_context \
  tests.test_t091_h_macro_header.HMacroHeaderTests.test_filelist_h_is_context_only_and_macro_provider_is_resolved \
  tests.test_t091_h_macro_header.HMacroHeaderTests.test_h_filelist_boundaries_fail_closed \
  tests.test_t098_authoritative_filelist \
  tests.test_t099_filelist_compile_context.T099FilelistCompileContextTests.test_filelist_order_headers_and_top_closure \
  tests.test_t099_filelist_compile_context.T099FilelistCompileContextTests.test_blocking_parse_and_semantic_errors_are_separate \
  tests.test_t117_filelist_v_library_source.T117FilelistVLibrarySourceTests.test_v_failures_are_exact_and_duplicate_with_bare_entry \
  tests.test_t118_vic_parameter_context.T118VicParameterContextTests.test_explicit_vic_is_parameter_context_prelude \
  tests.test_t118_vic_parameter_context.T118VicParameterContextTests.test_vic_reuses_filelist_path_rules \
  tests.test_t118_vic_parameter_context.T118VicParameterContextTests.test_vic_boundaries_fail_closed -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/source_set.py tests/test_t120_explicit_vic_include_reference.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T120_explicit_vic_include_reference.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t120_ready_for_review=pass")'
```

## 8. Formal verification

目标测试必须从组合 public CLI 生成 actual gate：

```text
formal_verification: PASS
gold-filelist: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t120-formal-ow0ird5l/gold.f
gold-root: /
gate-filelist: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t120-formal-ow0ird5l/gate/design.f
gate-root: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t120-formal-ow0ird5l/gate
top: t120_top
seq: 5
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t120-formal-ow0ird5l/gold.f --gold-root / --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t120-formal-ow0ird5l/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t120-formal-ow0ird5l/gate --top t120_top --seq 5
positive: exit 0; JSON {"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t120-formal-ow0ird5l/gate","gold":"/","seq":5,"top":"t120_top"}
negative: copied actual gate, changed one XOR to OR in child.v; strict compile exit 0; Formal exit 1 with unproven/equiv_status -assert
```

正例未通过、实际 gate 与 gold 相同、`.vic` 被改写、restore 非逐字节一致，或固定功能负例未被 Formal
拒绝时，不得设置 `READY_FOR_REVIEW`。

## 9. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 98cd9662d2889574f85aa4d4fa37a396a8ad48d3
started_at: 2026-08-31 11:26:50 +0800
first_command: git status --short && git rev-parse HEAD && git branch --show-current && sed -n '1,240p' AGENTS.md && sed -n '1,320p' docs/tasks/T120_explicit_vic_include_reference.md
starting_worktree: only untracked docs/tasks/T120_explicit_vic_include_reference.md (the Main Agent task contract)
allowed_files: AGENTS.md; README.md; docs/formal_verification.md; docs/development/project_structure.md; docs/systemverilog_renaming_table.md; docs/tasks/T120_explicit_vic_include_reference.md; rtl_obfuscator/source_set.py; tests/test_t120_explicit_vic_include_reference.py; tests/fixtures/t120_explicit_vic_include/**
changed_files: AGENTS.md; README.md; docs/formal_verification.md; docs/development/project_structure.md; docs/systemverilog_renaming_table.md; docs/tasks/T120_explicit_vic_include_reference.md; rtl_obfuscator/source_set.py; tests/test_t120_explicit_vic_include_reference.py; tests/fixtures/t120_explicit_vic_include/rtl/child.v
commands: baseline exact-match unittest (expected SOURCESET_UNSUPPORTED_FILE); then all five exact Section 7 commands, with the status guard run after this record update
results: baseline explicit same-path `.vic` + local include failed with SOURCESET_UNSUPPORTED_FILE at source_set.py:619; target 5/5 PASS; related regression 28/28 PASS; py_compile exit 0; git diff --check HEAD exit 0; public schema 2, rename>0, modified_tokens>0, strict_compile_passed=true, restored_byte_identical=true
schema_or_behavior: no schema or suffix-set change; authoritative include closure normalizes an existing `.vic` candidate and allows it only when that exact path is already in the bare explicit header/context set; `.vic` remains a single context prelude and is never a source or rename target
boundaries: direct module/compilation-unit, local, +incdir+, nested -f/environment, discovered `.h/.vh`, explicit `.svh`, and exact full-path matching PASS; include-only local/+incdir and same-basename different-path `.vic` retain the stable failure; `.VIC`, duplicate, `-v *.vic`, single-file and project-root remain closed; unsupported non-`.vic` symlink include candidates retain their prior ignore-before-normalization behavior
cleanup_candidates: none; no historical test or script changed
formal_verification: PASS; gold-filelist=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t120-formal-ow0ird5l/gold.f; gold-root=/; gate-filelist=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t120-formal-ow0ird5l/gate/design.f; gate-root=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t120-formal-ow0ird5l/gate; top=t120_top; seq=5; positive exit 0 and JSON formal_equivalence=pass; actual gate differs from gold; `.vic` and include text are unchanged; direct restore is byte-identical for all three physical inputs; negative actual-gate copy changed one XOR to OR in child.v, strict compile exit 0, Formal exit 1 with unproven/equiv_status -assert
uncovered_boundaries: no independent run on the user's `/library`/`/vol51` server paths; compact test uses temporary `.vic`/top plus committed `-v child.v` to force source_root=/; absolute-include lookup behavior is intentionally unchanged by contract
review_request: Main Agent please independently rerun all five Section 7 commands, inspect exact-path matching and the actual-gate Formal evidence, and confirm the normalization remains confined to `.vic` plus the pre-existing header branches; do not set ACCEPTED unless each result remains exact
```

## 10. 主 Agent 验收

```text
main_result: ACCEPTED
reviewed_at: 2026-08-31
reviewed_head: 98cd9662d2889574f85aa4d4fa37a396a8ad48d3
scope_review: PASS; changed paths are exactly the nine allowed T120 paths; rtl_files.py, project_discovery.py, mapping/rewrite/orchestration and historical tasks/tests are unchanged
implementation_review: PASS; only an existing lower-case .vic candidate is normalized and compared against the exact explicit header/context path set; .vic is not added to INCLUDE_CONTEXT_SUFFIXES; the pre-existing include-header branch retains its original normalization order
omission_review: PASS; direct and indirect include, local/+incdir+, nested -f/environment, same-basename different-path, include-only failure, non-.vic candidate preservation, T117 -v and T119 source_root=/ are covered
target_tests: PASS; 5/5
related_regression: PASS; 28/28
py_compile: PASS
diff_check: PASS
ready_for_review_guard: PASS before status transition
formal_verification: PASS
formal_gold_filelist: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t120-formal-be4awpoc/gold.f
formal_gold_root: /
formal_gate_filelist: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t120-formal-be4awpoc/gate/design.f
formal_gate_root: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t120-formal-be4awpoc/gate
formal_top: t120_top
formal_seq: 5
formal_positive: exit 0; JSON formal_equivalence=pass; actual gate differs from gold; .vic and include directive remain byte-identical; direct restore is byte-identical
formal_negative: copied actual gate and changed XOR to OR in child.v; strict compile exit 0; Formal exit 1 with unproven/equiv_status -assert
acceptance_note: during review, an initial implementation variant was found to normalize every existing include candidate before suffix filtering, which could have changed unrelated unsupported-suffix symlink behavior; the implementation was narrowed to the .vic branch and an explicit non-.vic regression was added before acceptance
```
