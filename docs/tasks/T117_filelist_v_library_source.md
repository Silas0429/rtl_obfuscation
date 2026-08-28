# T117：显式 filelist 支持 `-v PATH` 库源码条目

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 起始 HEAD：`91c5e346f11db0957c1026f79f7326e725b5d97d`（T116 已 `ACCEPTED`，工作树干净）
- 任务类型：SourceSet filelist 语法的最小兼容扩展

## 1. 单一目标

真实服务器 filelist 包含下列工业常见写法：

```text
-v /library/vendor/cell_model.v
```

当前 `_read_filelist()` 只识别 `-f`、`+incdir+` 和 `+define+`，会把该行拒绝为
`SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE`。本任务只新增 `-v PATH`：把 PATH 按出现位置加入现有
PySlang 编译顺序，并复用普通 `.sv/.v` source unit 的路径、闭包、rewrite、restore 和报告流程。

## 2. 冻结语义

1. 只接受同一行恰好两个空白分隔 token：`-v PATH`。
2. PATH 只允许小写 `.sv` 或 `.v` source unit；不存在时报 `SOURCESET_FILE_NOT_FOUND`。
3. PATH 复用普通 filelist entry 的 `$NAME`/`${NAME}` 展开、绝对路径、相对路径和嵌套 `-f` 基准规则。
4. `-v PATH` 在出现位置进入 `ordered_source_files`、`compile_order`、物理 manifest 和 PySlang compilation；
   mapping schema、四个 category、top closure 和既有 rename/preserve 判据不变。
5. `-v PATH` 当前等价于该位置的裸 `PATH` source entry。它不新增仿真器惰性 library search、
   duplicate-definition 优先级或专用 library metadata。
6. `-v` 无 PATH 报 `SOURCESET_INVALID_ARGUMENT`；多于一个 PATH、`-vPATH` 和其他 `-` 指令继续报
   `SOURCESET_UNSUPPORTED_FILELIST_DIRECTIVE`。
7. 裸路径、`-v` 与嵌套 filelist 最终指向同一物理文件时，继续报 `SOURCESET_DUPLICATE_FILE`。
8. CLI 文件缺失诊断必须能把 `-v PATH` 定位到实际 filelist 与行号。

## 3. 明确不包含

- 不支持 `-y`、`+libext+`、`-V`、`-vPATH` 或任何其他仿真器指令；
- 不支持 shell 引号、反斜杠转义、通配符或一行多个库文件；
- 不修改 filelist 自动 source-root 推导、跨 `/library` 与 `/vol*` 的多根目录策略；
- 不修改 PySlang 编译配置、category、RenameIndex、mapping schema、restore 或 Formal 工具；
- 不把库文件默认改成 context-only，也不增加按路径或文件名特判；
- 不运行 RISC-V-Vector Formal，不使用 blanket `unittest discover`。

## 4. 固定输入与可验收输出

新增 compact fixture：一个 `-v rtl/library_cell.v` 和一个普通 `rtl/top.sv`。顶层实例化 library cell，
必须完成公开 CLI actual gate、strict compile、byte-identical restore 和 Yosys Formal。

必须验证：

- `-v` 与同位置裸路径产生相同 SourceSet 顺序；
- 相对、绝对、环境变量和嵌套 `-f` 下的 `-v` 均走既有路径规则；
- 缺路径、额外 token、错误后缀、重复文件及 `-y` 精确 fail closed；
- 缺失 `-v` 文件的 CLI 错误包含 filelist 行号；
- actual gate 与 gold 字节不同，Formal 正例 exit 0 且 JSON `formal_equivalence=pass`；
- 固定功能负例 strict compile 通过但 Formal 非零。

## 5. 允许修改的文件

- `docs/tasks/T117_filelist_v_library_source.md`
- `rtl_obfuscator/source_set.py`
- `rtl_obfuscator/rewrite.py`
- `tests/test_t117_filelist_v_library_source.py`
- `tests/fixtures/t117_filelist_v_library_source/**`
- `README.md`

不得修改其他文件。

## 6. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t117_filelist_v_library_source -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_source_set tests.test_t090_filelist_context tests.test_t091_h_macro_header \
  tests.test_t093_macro_fallback_and_cli_validation tests.test_t094_builtin_preprocessor_macros \
  tests.test_t095_macro_formal_parameters tests.test_t098_authoritative_filelist \
  tests.test_t099_filelist_compile_context tests.test_public_cli -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py \
  tests/test_t117_filelist_v_library_source.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T117_filelist_v_library_source.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t117_ready_for_review=pass")'
```

## 7. Formal verification

任务产生实际改写 RTL，必须由目标测试生成 actual gate 并调用 `scripts/formal_equivalence.py`：

```text
formal_verification: PASS
gold: tests/fixtures/t117_filelist_v_library_source/bare.f
gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t117-formal-_r5f6inf/gate (temporary actual CLI gate)
top: t117_top
seq: 5
positive_command: python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t117_filelist_v_library_source/bare.f --gold-root tests/fixtures/t117_filelist_v_library_source --gate-filelist <temporary>/gate/design.f --gate-root <temporary>/gate --top t117_top --seq 5
positive: exit 0; JSON `formal_equivalence=pass`, `top=t117_top`
negative_command: python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t117_filelist_v_library_source/bare.f --gold-root tests/fixtures/t117_filelist_v_library_source --gate-filelist <temporary>/negative/design.f --gate-root <temporary>/negative --top t117_top --seq 5
negative: actual gate `library_cell.v` fixed mutation `1'b0 -> 1'b1`; iverilog strict compile exit 0; Formal exit 1 with `unproven` and `equiv_status -assert`
```

## 8. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 91c5e346f11db0957c1026f79f7326e725b5d97d
started_at: 2026-08-28 21:13:00 +0800
finished_at: 2026-08-28 21:18:05 +0800
starting_worktree: only untracked authorized task contract docs/tasks/T117_filelist_v_library_source.md
allowed_files: docs/tasks/T117_filelist_v_library_source.md; rtl_obfuscator/source_set.py; rtl_obfuscator/rewrite.py; tests/test_t117_filelist_v_library_source.py; tests/fixtures/t117_filelist_v_library_source/**; README.md
changed_files: docs/tasks/T117_filelist_v_library_source.md; rtl_obfuscator/source_set.py; rtl_obfuscator/rewrite.py; tests/test_t117_filelist_v_library_source.py; tests/fixtures/t117_filelist_v_library_source/{bare.f,design.f,rtl/library_cell.v,rtl/top.sv}; README.md
commands: baseline and the five exact commands in section 6; no blanket discovery or RISC-V-Vector Formal
results: baseline exit 1 due expected missing new test module; target unittest 4/4 pass; selected regression 42/42 pass; py_compile exit 0; `git diff --check HEAD` exit 0; READY_FOR_REVIEW guard prints `t117_ready_for_review=pass`
schema_or_behavior: `-v PATH` is normalized as the same source entry as bare PATH at that position; only `.sv/.v` is accepted; existing ordering, path expansion, duplicate detection, compile, rewrite, restore, mapping and category behavior is reused without schema change
boundaries: no `-y`, `+libext+`, `-V`, `-vPATH`, shell quoting/escaping/globbing, lazy library search, library metadata, multi-root strategy or Formal parser extension; Formal gold uses the proven-equivalent bare filelist while the gate is produced from the public CLI `-v` input
cleanup_candidates: none
formal_verification: PASS; actual renamed gate differs from gold; positive exit 0 and JSON pass; fixed functional negative strict compile exit 0 and Formal exit 1
review_request: Main Agent independently rerun the five commands in section 6; do not set ACCEPTED from this sub-agent record
```

## 9. 主 Agent 验收

```text
reviewed_at: 2026-08-28
reviewed_head: 91c5e346f11db0957c1026f79f7326e725b5d97d
allowlist: PASS；全部修改仅在第 5 节白名单内
commands:
  1) T117 目标模块             -> Ran 4 tests, OK, exit 0
  2) 指定 SourceSet/CLI 回归    -> Ran 42 tests, OK, exit 0
  3) py_compile                -> exit 0
  4) git diff --check HEAD     -> 无输出，exit 0
  5) READY_FOR_REVIEW 状态守卫 -> t117_ready_for_review=pass，exit 0
formal_positive:
  actual gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t117-formal-hhmbzfm7/gate
  gate 与 gold 字节不同；exit 0；JSON formal_equivalence=pass，top=t117_top，seq=5
formal_negative:
  actual gate 固定修改 library_cell.v 中 1'b0 -> 1'b1
  iverilog strict compile exit 0；Formal exit 1；unproven / equiv_status -assert
boundary_review: 仅增加 -v PATH 语法别名；不包含惰性 library search、其他库指令或多根目录策略
main_result: ACCEPTED
```
