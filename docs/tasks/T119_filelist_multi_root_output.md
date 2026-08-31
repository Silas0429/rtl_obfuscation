# T119：权威 filelist 多物理根输出路径校验

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 起始 HEAD：`9f6d6fc927857d2d725ccca0fa298b3e2f1f32e1`（T118 已 `ACCEPTED`，工作树干净）
- 任务类型：public filelist adapter + rewrite output boundary + compact actual-gate Formal
- 服务器证据：显式 filelist 同时引用 `/library/...` 与 `/vol51/...`，`infer_filelist_root(...) == Path("/")`；
  尚不存在的输出 `/home/maoyiming/workspace/test/test01` 被报为 `CLI_VNEXT_OUTPUT_INVALID`

## 1. 已确认的问题

public filelist 模式当前先将 filelist 自身、所有物理输入和 include 路径取 `commonpath` 作为内部
`source_root`。真实服务器输入跨 `/library`、`/vol51` 与工作目录，因此合法且可解析的 SourceSet
以 `/` 为相对路径边界。

CLI、orchestration 和 rewrite 三层都把整个 `source_root` 当作受保护目录。于是任何 Linux 绝对
输出路径都位于 `/` 下，即使目标尚不存在且不覆盖任何实际输入，也会被误判为 overlap。仅删除
CLI 检查会让同一输入随后在 orchestration/rewrite 层失败，不能解决目标问题。

## 2. 单一目标

让 `source_root == /` 的**权威 filelist 模式**按实际物理输入而不是全局根目录保护输出路径，使该
合法 filelist 能完成公开加密、actual gate、restore 和 Formal；非全局根 filelist、其他输入模式、
SourceSet 推导、相对输出布局和原子发布规则保持不变。

## 3. 冻结语义

1. `infer_filelist_root`、`SourceSet.source_root`、compile order 和 schema 均不改变；真实多根输入仍可
   合法得到 `/`，gate 的 canonical `design.f` 仍使用相对该根的稳定路径。
2. `origin == "filelist"` 且 `source_root == Path("/")` 时，CLI/orchestration/rewrite 不得仅因 output、
   restore 或显式 report 位于 `/` 下就拒绝；必须保护 SourceSet 中实际列出的
   source/header/context 物理文件。非全局根 filelist 保持既有完整 root fence。
3. filelist 输出目标与任何实际物理输入相同、包含该输入或位于一个文件输入之下时必须 fail closed；
   symlink、已存在目标、父目录不存在、gate/restore 互相 overlap、显式 map/metrics 与 output 或彼此
   overlap 的既有拒绝规则保持不变。
4. `single-file` 与 `project-root` 继续把整个 `source_root` 当作受保护目录；不得借本任务允许在源码树
   内发布 gate、restore、map 或 metrics。
5. authoritative filelist 的候选集合、top closure、`-v`、`.vic`、include、define、重复检测与编译
   顺序完全不变；不得增加扫描、fallback 或新的输入格式。
6. public CLI 的错误码、stdout JSON schema、portable report、atomic publish/rollback 和 direct decrypt
   合同不变。
7. 修复必须覆盖三层：public CLI 最终目标、orchestration 临时 gate/restore、rewrite actual gate；
   不得用把临时目录放到特殊位置的方式绕过。

## 4. 明确不包含

- 不改变 `infer_filelist_root`，不新增 `--source-root` 给 filelist 模式；
- 不扁平化或重写 `/library`、`/vol51` 对应的 root-relative gate 路径；
- 不放宽 project-root/single-file 输出边界；
- 不改变 `.v/.sv/.vh/.svh/.h/.vic` 或 `-v/-f/+incdir+/+define+` 语义；
- 不修改 mapping、metrics、orchestration、SourceSet schema 或 rename/preserve/unsupported 判定；
- 不新增配置项、兼容层、fallback、缓存或依赖；
- 不运行 RISC-V-Vector Formal，不使用 blanket `unittest discover`。

## 5. 固定 compact 输入与机器验收结果

新增 `tests/fixtures/t119_multi_root_filelist/rtl/child.sv`。目标测试在系统临时目录创建
`top.sv` 与绝对路径 filelist，并把 committed child 与临时 top 同时列入，使两者公共路径精确为 `/`。
输出为临时目录内尚不存在的 `test01`。

目标测试必须证明：

- `infer_filelist_root(filelist) == Path("/")`，且 output 在 `/` 下但不与任何实际输入物理路径重叠；
- 公开 `rtl_encrypt.py --filelist ... --top t119_top --category all --output-dir test01` exit 0，
  stdout schema 保持 2，rename/modified token 大于 0，strict compile 与 restore-byte-identical 为 true；
- actual gate 的 canonical `design.f` 同时保存两条 root-relative 物理路径，gate 与 direct restore 对
  两个输入逐字节审计通过；实际改名 gate 与 gold 不同；
- actual gate Formal 正例 exit 0 且 JSON `formal_equivalence=pass`；固定 XOR→OR 功能负例 strict compile
  exit 0、Formal 非零并含 `unproven` / `equiv_status -assert`；
- output 已存在、父目录缺失、filelist output/report 冲突继续精确返回 `CLI_VNEXT_OUTPUT_INVALID` 且无
  部分产物；同一布局改用 project-root 时，源码根内的 output 继续被拒绝；
- 目标测试必须经过实现前反向确认：当前 HEAD 至少因 `CLI_VNEXT_OUTPUT_INVALID` 失败。

## 6. 允许修改的文件

- `README.md`
- `docs/development/project_structure.md`
- `docs/tasks/T119_filelist_multi_root_output.md`
- `rtl_obfuscator/rewrite.py`
- `rtl_obfuscator/orchestration_vnext.py`
- `rtl_obfuscator/rewrite_vnext.py`
- `tests/test_t119_filelist_multi_root_output.py`
- `tests/fixtures/t119_multi_root_filelist/**`

不得修改其他文件。不得修改 `rtl_obfuscator/source_set.py` 或其 root 推导规则。

## 7. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t119_filelist_multi_root_output -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_public_cli tests.test_rewrite_vnext tests.test_orchestration_vnext \
  tests.test_t090_filelist_context tests.test_t093_macro_fallback_and_cli_validation \
  tests.test_t098_authoritative_filelist \
  tests.test_t117_filelist_v_library_source.T117FilelistVLibrarySourceTests.test_v_failures_are_exact_and_duplicate_with_bare_entry \
  tests.test_t118_vic_parameter_context.T118VicParameterContextTests.test_vic_boundaries_fail_closed -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rewrite.py rtl_obfuscator/orchestration_vnext.py rtl_obfuscator/rewrite_vnext.py \
  tests/test_t119_filelist_multi_root_output.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T119_filelist_multi_root_output.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t119_ready_for_review=pass")'
```

### 7.1 主 Agent review correction

第一版 review 暴露两个合同问题，已在进入主验收前纠正并退回 `IN_PROGRESS`：

1. T119 的服务器目标精确是 `source_root == /`。为不顺带改变已由
   `tests.test_rewrite_vnext` 固定的非全局 filelist root fence，§2/§3 收窄为只对全局根 filelist
   使用实际物理输入保护。
2. 原固定回归误列 `tests.test_t092_filelist_input_mode`；该模块在起始 HEAD 已因仍断言 source-only
   `compile_order` 而失败，与已接受的 T099 context-prelude 合同冲突，不是 T119 回归。将它替换为
   当前有效且覆盖 filelist context/error 不变量的 `tests.test_t090_filelist_context`。

子 Agent 必须复跑修正后的五条命令、把 §8 从 `PENDING` 同步为实际 Formal 证据，并且只有全部通过后
才能再次设置 `READY_FOR_REVIEW`。

## 8. Formal verification

目标测试必须从公开 CLI 的多根 filelist 生成 actual gate，并记录：

```text
formal_verification: PASS
gold-filelist: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/design.f
gold-root: /
gate-filelist: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/test01/design.f
gate-root: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/test01
top: t119_top
seq: 5
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/design.f --gold-root / --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/test01/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/test01 --top t119_top --seq 5
exit_code: 0
result: {"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/test01","gold":"/","seq":5,"top":"t119_top"}
negative: copied actual gate, changed one XOR to OR in child.sv; strict compile exit 0; Formal exit 1 with unproven/equiv_status -assert
```

正例未通过、gate 与 gold 相同、restore 非逐字节一致、或固定负例未被 Formal 拒绝时，不得设置
`READY_FOR_REVIEW`。

## 9. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 9f6d6fc927857d2d725ccca0fa298b3e2f1f32e1
started_at: 2026-08-31 10:54:44 +0800
first_command: 2026-08-31 10:54:44 +0800; pwd && rg --files ...; git status --short --branch && git rev-parse HEAD
starting_worktree: only the Main Agent task contract is untracked
allowed_files: see Section 6
changed_files: README.md; docs/development/project_structure.md; docs/tasks/T119_filelist_multi_root_output.md; rtl_obfuscator/rewrite.py; rtl_obfuscator/orchestration_vnext.py; rtl_obfuscator/rewrite_vnext.py; tests/test_t119_filelist_multi_root_output.py; tests/fixtures/t119_multi_root_filelist/rtl/child.sv
commands: baseline target unittest (before implementation, expected failure); corrected five exact Section 7 commands, with the status guard run after this record update
results: baseline target failed at public encryption with CLI_VNEXT_OUTPUT_INVALID while infer_filelist_root(filelist) was /; corrected T119 target 1/1 PASS; corrected related regression 23/23 PASS; py_compile exit 0; git diff --check HEAD exit 0; output-existing/missing-parent/report-conflict/symlink/project-root boundary checks PASS
schema_or_behavior: no SourceSet, root inference, compile order, or report schema change; only filelist with source_root=/ protects resolved physical source/header/context files at CLI, orchestration, mapping-output, actual gate, and temporary restore boundaries; non-global filelist roots and single-file/project-root retain full source-root protection; direct public restore path validation remains unchanged
boundaries: `.vic`, include closure, duplicate detection, `-v`, top closure, compile order, and report portability are delegated unchanged to SourceSet; output targets must be new with an existing parent; direct restore continues to protect gate/map paths through the unchanged restore adapter; mapping-output protection uses the same source_root=/ special case and otherwise preserves the original root fence
cleanup_candidates: none; no out-of-scope files changed and no generated artifacts remain
formal_verification: PASS; gold-filelist=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/design.f; gold-root=/; gate-filelist=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/test01/design.f; gate-root=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/test01; top=t119_top; seq=5; positive command `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/design.f --gold-root / --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/test01/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/test01 --top t119_top --seq 5`, exit 0, JSON `{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-0yiqyo_e/test01","gold":"/","seq":5,"top":"t119_top"}`; fixed XOR->OR actual-gate negative strict compile exit 0, Formal exit 1 with `unproven` and `equiv_status -assert`
uncovered_boundaries: no independent server `/library` + `/vol51` paths; compact test uses committed child plus temporary top to force source_root=/; mapping/metrics custom reports are covered for overlap rejection, not successful publication under source_root=/
review_request: Main Agent please independently rerun all five corrected Section 7 commands and inspect the actual-gate Formal evidence; all corrected results pass, and the sub-agent does not set ACCEPTED
```

## 10. 主 Agent 验收

```text
main_result: ACCEPTED
reviewed_at: 2026-08-31
reviewed_head: 9f6d6fc927857d2d725ccca0fa298b3e2f1f32e1
scope_review: PASS; all 8 changed/new paths are inside the Section 6 allowlist; source_set.py is unchanged
contract_correction_review: PASS; the stale T092 baseline and global-root-only scope correction are recorded in Section 7.1
target_tests: 1/1 PASS
related_regression: 23/23 PASS
py_compile: exit 0
diff_check: exit 0
ready_for_review_guard: t119_ready_for_review=pass (run before this ACCEPTED transition)
formal_positive: exit 0; JSON formal_equivalence=pass; gold-root=/; actual gate=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t119-multi-root-tf0e14jq/test01
formal_negative: copied actual gate; XOR-to-OR mutation in child.sv; strict compile exit 0; Formal exit 1 with unproven/equiv_status -assert
boundary_review: PASS; only authoritative filelist with source_root=/ uses physical-input protection; non-global filelist, single-file, and project-root retain the full root fence; existing/symlink/missing-parent/report-conflict targets remain fail closed
```
