# T137：原序 filelist 路径视图

- 状态：`ACCEPTED`
- 负责人：子 Agent（实现与自测）/ 主 Agent（合同与验收）
- 起始分支：`delivery/fast-local-signals`
- 起始提交：`8173112bd5c3ad8765d69d55f49dd160d9544bf6`

## 1. 单一目标

修正 T136 的三视图 filelist 生成方式：不再从 SourceSet 的 `include_dirs + defines + compile_order`
重新组装，而是以用户传入的原始 filelist 文本及其 nested `-f` 文本为唯一模板，仅替换其中的路径
token。不得改变 SourceSet、FAST/FULL、候选对象、rename/preserve/unsupported、MappingVNext schema、
RTL edits、strict compile、manifest 或 byte-identical restore。

本合同只改变公开 `--filelist` 输入模式。`--input` 与 `--source-root + --top` 没有用户提供的原始
filelist，继续使用 T136 的 canonical 三视图行为。

## 2. 固定输入

主 Agent 冻结以下黑盒测试，子 Agent 不得修改：

```text
tests/test_t137_filelist_path_only_views.py
```

测试动态建立一个包含注释、空行、`-v`、nested `-f`、`+incdir+`、`+define+` 和普通 source entry
的 SystemVerilog 工程。输入 filelist 的条目顺序刻意不是 SourceSet 规范输出的分组顺序。

## 3. 三个顶层 filelist 合同

### 3.1 `original_design.f`

- 必须与 CLI `--filelist` 指定的顶层文件逐字节完全一致；
- 不展开环境变量，不规范化路径，不改变空白、注释、空行、换行、指令或条目顺序；
- nested `-f` 继续指向原始 nested filelist。

### 3.2 `design.f`

- 保持顶层原始文件的全部行、顺序、指令、非路径文字和条目数量；
- bare source/context、`-v PATH` 和 `+incdir+PATH` 的路径替换为 `<absolute OUT>/<SourceSet 相对路径>`；
- `-f PATH` 保持 `-f`，路径替换为输出内对应 design nested 镜像的绝对路径；
- 禁止新增由 CLI `--include-dir` / `--define` 提供但原 filelist 中不存在的指令。

### 3.3 `export_design.f`

- 与 `design.f` 一一对应并保持同一文本结构；
- physical source/context/include 路径替换为 `$OUT/<SourceSet 相对路径>`；
- `-f PATH` 指向 `$OUT` 下对应 export nested 镜像；
- `$OUT` 必须保持字面量，运行 EDA/Formal 前由环境展开。

## 4. nested `-f` 合同

为同时保证 `design.f` 的绝对自包含和 `export_design.f` 的可移动性，输出两套内部镜像：

```text
<OUT>/.rtl_obfuscation/filelists/design/<原 nested filelist 的 SourceSet 相对路径>
<OUT>/.rtl_obfuscation/filelists/export/<原 nested filelist 的 SourceSet 相对路径>
```

- 两套 nested 镜像都递归保持各自原始 filelist 的全部行、顺序、指令、非路径文字和条目数量；
- design 镜像使用最终 OUT 绝对路径，export 镜像使用 `$OUT`；
- nested `-f` 不得扁平化；`-v` 标志不得丢失；
- comments / blank lines / `+define+` 原样保留；
- 多路径 `+incdir+A+B` 必须保持同一行和路径次序，只逐个替换路径；
- literal include-only 文件继续复制，但不得因此增加任何 filelist 条目；
- 输出目录不得出现未被 design/export `-f` 闭包引用的额外 nested filelist。

## 5. 不包含

- 不支持 SourceSet 当前不接受的 shell/filelist 语法；
- 未转义且路径 token 含空白的 `+incdir+` 属于无法无歧义重放的输入，必须在 SourceSet 阶段
  fail-closed；本任务不增加引号、反斜杠或空格路径兼容层；
- 不改变原 filelist 重复条目的既有拒绝规则；
- 不把 CLI 单独传入的 `--include-dir` / `--define` 注入输出 filelist；调用下游工具时仍需单独传入；
- 不改变 summary、metrics 或 mapping schema；
- 不运行 AICluster/StCache 或 RISC-V-Vector Formal；
- 子 Agent 不提交、不推送。

## 6. 恢复与 Formal

- public decrypt 接受固定三个顶层文件及 design/export `-f` 闭包内的内部镜像；仍拒绝无引用的额外文件；
- filelist 文本不是 RTL manifest，不能因无法从 mapping 重建原始空白而放宽物理 RTL manifest/range 审计；
- `scripts/formal_equivalence.py` 必须按出现顺序递归处理 `-f`，把 `-v PATH` 作为 source entry，
  保留 `+incdir+` / `+define+` 上下文；gold 和 gate 分别解析；
- compact actual renamed gate 正例必须通过；把 gate 中 XOR 改为 OR 的固定负例必须非零并包含
  `unproven` 与 `equiv_status -assert`；复制 gate 后设置新 `OUT`，通过 `export_design.f` 的正例必须通过。

## 7. 允许修改文件

```text
README.md
docs/development/project_structure.md
docs/formal_verification.md
docs/tasks/T137_filelist_path_only_views.md
rtl_obfuscator/source_set.py
rtl_obfuscator/rewrite.py
rtl_obfuscator/restore_vnext.py
scripts/formal_equivalence.py
tests/test_formal_equivalence.py
tests/test_t116_cli_report.py
tests/test_t119_filelist_multi_root_output.py
tests/test_t134_fast_include_closure.py
tests/test_t136_persisted_run_summary_and_filelists.py
```

固定黑盒测试不在子 Agent 允许修改列表。需要修改其他生产文件、mapping schema、RTL fixture 或 rename
实现时，记录偏差并停止。

## 8. Baseline

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t137_filelist_path_only_views -v
```

预期失败：T136 会重新分组并规范化三份 filelist、丢失 `-v` / nested `-f` / comments / blank lines，且
`original_design.f` 不与输入逐字节一致。

## 9. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t137_filelist_path_only_views \
  tests.test_t136_persisted_run_summary_and_filelists \
  tests.test_t119_filelist_multi_root_output \
  tests.test_t134_fast_include_closure \
  tests.test_formal_equivalence -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py \
  rtl_obfuscator/restore_vnext.py scripts/formal_equivalence.py \
  tests/test_t137_filelist_path_only_views.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T137_filelist_path_only_views.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t137_ready_for_review=pass")'
```

## 10. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 8173112bd5c3ad8765d69d55f49dd160d9544bf6
first_command: conda run -n rtl_obfuscation python -m unittest tests.test_t137_filelist_path_only_views -v
allowed_files: README.md; docs/development/project_structure.md; docs/formal_verification.md; docs/tasks/T137_filelist_path_only_views.md; rtl_obfuscator/source_set.py; rtl_obfuscator/rewrite.py; rtl_obfuscator/restore_vnext.py; scripts/formal_equivalence.py; tests/test_formal_equivalence.py; tests/test_t116_cli_report.py; tests/test_t119_filelist_multi_root_output.py; tests/test_t134_fast_include_closure.py; tests/test_t136_persisted_run_summary_and_filelists.py
changed_files: README.md; docs/development/project_structure.md; docs/formal_verification.md; docs/tasks/T137_filelist_path_only_views.md; rtl_obfuscator/source_set.py; rtl_obfuscator/rewrite.py; rtl_obfuscator/restore_vnext.py; scripts/formal_equivalence.py; tests/test_formal_equivalence.py; tests/test_t134_fast_include_closure.py; tests/test_t136_persisted_run_summary_and_filelists.py. Main Agent frozen tests/test_t137_filelist_path_only_views.py remained unmodified by the sub-agent.
commands: baseline target; fixed 5-module unittest matrix; fixed py_compile; git diff --check HEAD.
results: baseline failed in the three expected T136 reconstruction areas; final unittest matrix PASS, 19 tests; py_compile PASS; diff check PASS. T137 verifies byte-identical original top filelist, path-only top/nested design/export views, -v/-f/comments/blank lines, multi-path +incdir+, source-after-context original order, public decrypt, relocated export Formal, and functional negative.
schema_or_behavior: public --filelist publication now renders from accepted original top/nested bytes and changes only path tokens; internal --input, --source-root + --top, SourceSet report, MappingVNext schema, candidate decisions and RTL edits are unchanged. Formal recursively consumes -f in place and treats -v as a source entry. Public restore admits only referenced nested mirrors and validates design/export structure, physical membership, source order and include membership.
boundaries: CLI-only --include-dir/--define are intentionally not injected; a regression verifies that such a gate still decrypts. With mapping schema unchanged, restore cannot distinguish a CLI-only include from a nested filelist include synchronously deleted from both delivery views; this metadata limitation does not relax RTL manifest/range/byte-restore audits, and unreferenced extra nested files remain rejected. Unquoted +incdir paths containing whitespace (including whitespace introduced by environment expansion) now fail closed at SourceSet because no quoting/backslash compatibility layer exists. The pre-existing strict-gate limitation for a completely empty unused include directory was observed but not changed; the frozen multi-incdir fixture uses real include dependencies. No AICluster/StCache/RISC run was performed.
cleanup_candidates: none
formal_verification: PASS
gold: dynamically created T137 project via gate/original_design.f; gate: actual renamed gate/design.f and relocated gate/export_design.f; top: t137_top; seq: 5
command: conda run -n rtl_obfuscation python -m unittest tests.test_t137_filelist_path_only_views.T137FilelistPathOnlyViewsTests.test_actual_gate_and_relocated_export_formal_with_negative -v
exit_code: 0
result: design positive exit 0 with formal_equivalence=pass; relocated export positive exit 0 with formal_equivalence=pass; fixed gate XOR-to-OR negative returned nonzero and contained unproven plus equiv_status -assert.
review_request: Main Agent should independently rerun section 9 and inspect the output filelist bytes before ACCEPTED.
```

## 11. 偏差或阻塞

```text
baseline: 5 tests ran; expected failures were original_design byte inequality,
reconstructed design/export text inequality, and missing nested mirrors. Existing
encryption, public decrypt, and normalized-list Formal remained operational.
```

## 12. 主 Agent 验收记录

```text
status: ACCEPTED
review_baseline: 8173112bd5c3ad8765d69d55f49dd160d9544bf6
scope_review: PASS; all production, documentation, and regression changes are within the authorized T137 list. The frozen main-agent black-box was extended only with a nested-filelist symlink-escape regression after code review; no production scope was added.
acceptance_command: conda run -n rtl_obfuscation python -m unittest tests.test_t137_filelist_path_only_views tests.test_t136_persisted_run_summary_and_filelists tests.test_t119_filelist_multi_root_output tests.test_t134_fast_include_closure tests.test_formal_equivalence -v
acceptance_result: PASS; 20 tests in 2.698s.
syntax_command: conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py scripts/formal_equivalence.py tests/test_t137_filelist_path_only_views.py
syntax_result: PASS.
diff_command: git diff --check HEAD
diff_result: PASS.
filelist_evidence: original_design.f is byte-identical to the top input; design.f and export_design.f preserve comments, blank lines, directives, entry count, -v, -f, multi-path +incdir+, and the deliberately non-canonical explicit .vic position. Nested design/export mirrors preserve their own order and structure, and no literal include-only entry is injected.
restore_evidence: public decrypt restores all physical inputs byte-identically, rejects an external nested-filelist symlink, and admits no unreferenced nested mirror.
formal_verification: PASS; actual renamed gate/design.f and relocated gate/export_design.f both returned formal_equivalence=pass for top t137_top with seq=5. The fixed XOR-to-OR gate mutation returned nonzero and reported unproven plus equiv_status -assert.
accepted_boundary: CLI-only include-dir/define remain outside all three filelist views by contract; downstream consumers must receive them separately. Mapping schema and rename behavior are unchanged. AICluster/StCache and RISC-V-Vector were not run by this compact task.
```
