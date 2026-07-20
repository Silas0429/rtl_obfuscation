# T032：`project-root + top` Parameter rewrite 闭环

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T031 `ACCEPTED`
- 基线提交：`e75b7fd`
- Formal verification：必须 `PASS`
- 关联草案：[`docs/project_root_parameter_plan_draft.md`](../project_root_parameter_plan_draft.md)
- T031 fixture：只读，不得修改

## 1. 单一目标

把 T031 已验收的 module-scoped parameter/localparam inventory 接入
`project-root + top` 的加密闭环：

1. 显式 `--category parameters` 可以加密；
2. eligible declaration/reference ranges 改写为随机名称；
3. top parameter、macro parameter-like object 和 unsupported boundary 保持安全分类；
4. gate 使用同一闭包、编译上下文和 category 做 strict reanalysis；
5. mapping v3、manifest、per-file mapping、metrics、decrypt 和逐文件字节恢复闭环；
6. 参数重写后的 RTL 通过 Yosys formal 正例，功能变更负例必须失败；
7. 默认五组 profile、legacy filelist/single-file parameter behavior 和 T031 oracle 保持不变。

T032 不实现 type parameter、package/class/interface parameter declaration、`defparam`、
复杂 hierarchical reference 或 struct 作为 parameter 类型输入。

## 2. 子 Agent 行为规范

开始前必须阅读 `AGENTS.md`、`docs/tasks/README.md`、T027/T028/T029/T030/T031、
`docs/project_root_parameter_plan_draft.md`、`docs/formal_verification.md`、
`docs/systemverilog_renaming_table.md`、`README.md` 和本合同。

然后必须：

1. 确认 T032 是唯一 `READY` 任务，没有其他 `IN_PROGRESS` 或 `READY_FOR_REVIEW`；
2. 主 Agent 冻结 formal companion fixture、hash 和 oracle 后，将本文件从 `READY` 改为 `IN_PROGRESS`；
3. 在执行记录中写明开始时间、HEAD、首条命令、继承工作区和所有输入 hash；
4. 严格按 Phase A → B → C → D → E 执行，阶段失败立即停止；
5. 只修改“允许修改的文件”；
6. 所有 Python、PySlang、Verible、Icarus、Yosys 和测试命令使用 `conda run -n rtl_obfuscation`；
7. 不修改 T031 正例/负例 fixture、T030 fixture、FIFO、RISC-V-Vector、旧 formal inputs 或旧 oracle；
8. 不删除 strict gate reanalysis、manifest/range audit、decrypt hash、per-file mapping 或 formal negative；
9. 不 commit、push、设置 `ACCEPTED` 或创建 T033；
10. 完成后填写 exact commands、exit code、JSON、hash、formal 正负结果、未覆盖边界，并设置 `READY_FOR_REVIEW`。

发现需要扩大到 package/class/interface parameter、改变 top ABI、放宽 T031 oracle 或修改
Yosys formal view 时，必须写入“偏差或阻塞”并等待主 Agent，不得自行扩大范围。

## 3. 固定输入与预期结果

### 3.1 T031 gold fixture

只读输入：`tests/fixtures/t031_project_root_parameters/`。

固定 closure：

```text
files: bus_if.sv, child.sv, top.sv
modules: parameter_child, parameter_top
interfaces: bus_if
parameter entries: 7 eligible / 3 preserved
eligible occurrences: 19
input manifest (closure files only): 5184e50aeb8c397bea70c8217b35e7d1192b75b3742a6b3cc4ce4875ff3c64b6
```

T031 固定 range digest 必须保持：

```text
eligible: 0a602a2aa4eee4899707481c927b0620025b0f1561e4ff76dfe0dc780096f6f4
preserved: 33d7a2f06c13d3c9534fa51c7a7134dba9fbffdca737075f0506a864c4905bc3
all: 44f893c8cd48d1031236155113e83b89beaed9cb0dc244e2b7a4717aaafde056
```

### 3.2 Parameter-only encrypt contract

命令：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --project-root tests/fixtures/t031_project_root_parameters \
  --top parameter_top \
  --output-dir /tmp/t032-parameter/gate \
  --map /tmp/t032-parameter/mapping.json \
  --metrics /tmp/t032-parameter/metrics.json \
  --file-map-dir /tmp/t032-parameter/maps \
  --category parameters \
  --name-length 8
```

固定 stdout 摘要：

```json
{"files":3,"mapping_entries":7,"modified_tokens":19}
```

mapping v3 必须满足：

- `mode="project-root"`、`version=3`、`top="parameter_top"`；
- `selected_groups=["parameters"]`；
- `selected_categories=["parameters"]`；
- `files=["bus_if.sv","child.sv","top.sv"]`；
- `input_manifest_sha256=5184e50aeb8c397bea70c8217b35e7d1192b75b3742a6b3cc4ce4875ff3c64b6`；
- `entries` 恰好为 T031 的 7 个 eligible symbols；
- `preserved` 恰好包含 DATA_WIDTH、LANES、MACRO_LOCAL 及既有 reason；
- 每个 original range 在 gold 中仍等于原名，每个 gate range 等于 8 字符 renamed name；
- renamed names 唯一、合法、不为 SystemVerilog keyword，且不与 preserved spelling 冲突；
- `gate_manifest_sha256` 必须按实际 gate closure 文件重新计算，不能复制 input manifest。

具体随机名称不冻结；验收依据 mapping/range/occurrence 关系、名称合法性和 gate 审计。

### 3.3 Gate strict reanalysis

对 gate 运行：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root /tmp/t032-parameter/gate \
  --top parameter_top \
  --report /tmp/t032-parameter/gate-report.json \
  --category parameters
```

必须满足：

- status 为 `pass`；
- parse/semantic errors 为 0；
- module/interface/file topology 与 gold 一致；
- gate eligible symbol/occurrence 数仍为 7/19；
- top parameters 仍为 preserved；
- macro-generated object 仍为 preserved 且无物理 declaration；
- gate inventory 与 mapping 的 renamed spelling/range 完全一致。

### 3.4 Metrics、per-file mapping 和 decrypt

必须满足：

- symbol coverage = 1.0；
- occurrence coverage = 1.0；
- effective coverage = 1.0；
- plaintext leakage rate = 0.0；
- per-file mapping occurrence 并集等于 global mapping occurrence；
- 没有 eligible occurrence 的 `bus_if.sv` 可以不生成空 per-file map；
- decrypt-project 不需要 `--source-root`；
- `bus_if.sv`、`child.sv`、`top.sv` 全部恢复且逐字节等于 T031 gold。

## 4. Formal companion fixture

T031 fixture 含 interface/packed struct，不能直接假设 Yosys 0.53 支持全部语法。T032 在
从 `DRAFT` 改为 `READY` 前，主 Agent 必须冻结一份仅用于 formal 的小型 project-root fixture：

```text
tests/formal/t032_project_root_parameters/
├── design.f
├── child.sv
└── top.sv
```

主 Agent 已冻结该 fixture：

- 只含 module、简单 integral parameter/localparam、packed dimension、named override；
- 不含 interface、struct、package、class、assertion 或 unsupported parameter；
- top parameter 保留，child parameter/localparam 可改写；
- gold/gate 使用同一 top 和同一 filelist；
- `child.sv`：382 bytes，`57e9398d782a9d6efc2f14ecd13f0ef5ace6417d479bc3487f6fe4bafcacb34e`；
- `design.f`：16 bytes，`b5d10edc287c7f96e0759fef7fb91508742be8bb991214e7ec16ad09bfc7d3f6`；
- `top.sv`：486 bytes，`d00624a35124ceea97073a8f12c546c4a741cb47b4cd5c098177e2ddf8c5957e`；
- formal input manifest：`2fa02a5d1523a1e8d2ebf891f33bf2fa26818c8b9152de3ae23dab53c7537c81`；
- `top=t032_top`、默认 `seq=5`；
- 预期正例 JSON：`{"formal_equivalence":"pass","gate":"<gate-root>","gold":"tests/formal/t032_project_root_parameters","seq":5,"top":"t032_top"}`；
- 预期负例：exit non-zero，`equiv_status -assert` 报告 unproven `$equiv`，不能以 parse failure 作为通过。

冻结前基线检查：PySlang syntax/semantic `0/0`、Verible exit `0`、Icarus exit `0`、Yosys gold `prep/hierarchy -check` exit `0`。手工参数改名 gate formal 正例 exit `0` 并输出 `formal_equivalence=pass`；将 gate 输出改为 `~child_data` 的功能负例 exit `1`，报告 8 个 unproven `$equiv`。

Formal 正例：对 gold 与真实 parameter gate 运行 `scripts/formal_equivalence.py`，必须退出 0 并输出 `formal_equivalence=pass`。

功能负例：只把 gate 中一个 arithmetic operation 改成非等价逻辑，必须退出非 0，不能把 parse failure 当作负例通过。

## 5. CLI 兼容性

### 5.1 Default profile

省略 `--category` 仍只启用：

```text
signals ports instances struct interface
```

T030 FIFO/RISC 默认 oracle 不变。T032 不把 parameters 纳入默认 profile。

### 5.2 Combined profile

以下组合必须支持并保持 category canonical order：

```text
signals ports instances struct interface parameters
```

组合 gate 必须通过 strict reanalysis，parameter entries 与 T031 oracle 完全一致，其他 category 的既有 entry 不得被 parameter ranges 重复占用。具体 combined totals 不作为新随机名称 oracle，只检查每类 entry、range、coverage 和恢复结果。

### 5.3 Legacy compatibility

- legacy single-file `encrypt --category parameters` 继续通过；
- legacy filelist v2 不改变；
- `inspect-project --category parameters` 继续支持 T031 inventory；
- 不新增 mapping version，不改变 decrypt-project v2/v3 schema。

## 6. 允许修改的文件和禁止事项

允许修改：

- `rtl_obfuscator/rewrite.py`：project-root parameter CLI validation、rewrite、mapping/gate/decrypt integration；
- `rtl_obfuscator/project.py` 或 `rtl_obfuscator/inventory.py`：仅限 T031 已证明缺口的最小修正；
- `tests/test_project_root_parameter_rewrite.py`；
- `tests/test_project_root_parameters.py` 和 `tests/test_project_root_rewrite.py` 中仅用于把 T031/T028 旧的“parameters 必须拒绝”断言同步为 T032 显式 rewrite 合同的兼容性断言；
- `tests/fixtures/t032_project_root_parameters/**` 或主 Agent 冻结的 `tests/formal/t032_project_root_parameters/**` formal companion；
- `docs/tasks/T032_project_root_parameter_rewrite.md` 的执行记录；
- T032 接受后由主 Agent同步 README/roadmap/status 文档。

禁止：

- 修改 T031 gold/negative fixture 或 T031 range digest；
- 修改 T030/FIFO/RISC fixtures 或既有 formal inputs；
- 默认启用 parameters；
- 修改 top parameter spelling；
- 通过忽略 preserved/unsupported 对象、降低 coverage、跳过 strict audit 或删除负例制造通过；
- 把 T033 的 RISC-V-Vector 参数集成、formal-view 扩展或默认 profile 晋级混入 T032。

## 7. 分阶段执行门禁

### Phase A：API 和 rewrite probe

确认 parameter declaration/reference range 可以直接复用 T031 inventory，随机名称应用只覆盖 eligible ranges，preserved ranges 不产生 edit。验证 parameter ranges 与其他 category 不重叠。

### Phase B：参数-only rewrite

实现 3 files / 7 entries / 19 tokens 的 encrypt、strict gate reanalysis、mapping v3、metrics、per-file mapping 和 decrypt 闭环。

### Phase C：combined/compatibility

验证 default 五组、五组 + parameters、legacy single-file/filelist、T031 inspect 和旧 T030/T027/T028/T029 回归。

### Phase D：formal

冻结 formal companion hash；运行 gold/gate formal 正例和功能负例；记录完整 command、exit code、JSON 和资源异常。formal 失败、跳过或只做 identity comparison 时不得申请 review。

### Phase E：交付记录

填写 changed files、exact commands、summary JSON、mapping/metrics digest、manifest、decrypt hash、formal 正负结果、未覆盖边界，并设置 `READY_FOR_REVIEW`。

## 8. 固定验收命令模板

主 Agent 在冻结 formal companion 后，将所有 `<...>` 替换为实际路径和固定 oracle。

```sh
conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project.py rtl_obfuscator/inventory.py rtl_obfuscator/rewrite.py \
  tests/test_project_root_parameter_rewrite.py

conda run -n rtl_obfuscation python -m unittest \
  tests.test_project_root_parameter_rewrite \
  tests.test_project_root_parameters \
  tests.test_project_root_inspect \
  tests.test_project_root_rewrite \
  tests.test_project_root_low_risk -v

conda run -n rtl_obfuscation python -m unittest discover -s tests -v
```

Formal command模板：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist tests/formal/t032_project_root_parameters/design.f \
  --gold-root tests/formal/t032_project_root_parameters \
  --gate-filelist /tmp/t032-formal/gate/design.f \
  --gate-root /tmp/t032-formal/gate \
  --top t032_top
```

## 9. READY_FOR_REVIEW 门禁

子 Agent 只有同时满足以下条件才能申请 review：

1. T031 gold/negative fixture hash 和 digest 未变化；
2. parameters-only 输出精确为 3 files / 7 entries / 19 modified tokens；
3. mapping v3、strict gate、metrics、per-file mapping、decrypt 全部通过；
4. preserved top/macro 和 unsupported boundary 有独立证据；
5. default 五组、combined profile、legacy v2/v1、T030/T027/T028/T029 回归通过；
6. formal companion 正例 PASS、功能负例 FAIL；
7. py_compile、Verible、Icarus、git diff --check 通过；
8. exact commands、exit codes、JSON、hash、uncovered boundaries 已写入任务单；
9. 状态改为 `READY_FOR_REVIEW`，不得设置 `ACCEPTED`、commit 或 push。

## 10. Formal verification 记录格式

```text
formal_verification: PASS
gold: tests/formal/t032_project_root_parameters/design.f / tests/formal/t032_project_root_parameters
gate: /tmp/t032-formal/gate/design.f / /tmp/t032-formal/gate
top: t032_top
command: `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/formal/t032_project_root_parameters/design.f --gold-root tests/formal/t032_project_root_parameters --gate-filelist /tmp/t032-formal/gate/design.f --gate-root /tmp/t032-formal/gate --top t032_top`
exit_code: 0
result: {"formal_equivalence":"pass","gate":"/tmp/t032-formal/gate","gold":"tests/formal/t032_project_root_parameters","seq":5,"top":"t032_top"}
negative_command: `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/formal/t032_project_root_parameters/design.f --gold-root tests/formal/t032_project_root_parameters --gate-filelist /tmp/t032-formal/negative/design.f --gate-root /tmp/t032-formal/negative --top t032_top`
negative_exit_code: 1
negative_result: Yosys reached `equiv_status -assert` and reported 8 unproven `$equiv` cells after intentional output inversion.
```

## 11. 执行记录

formal companion hash/oracle 已在第 4 节冻结。子 Agent 开始后填写：

```text
start_time: 2026-07-20 13:25:16 CST
head: e75b7fdcbf78469284bdade3195b92a082ce4570
first_command: `sed -n '1,260p' docs/tasks/README.md; sed -n '1,420p' docs/tasks/T032_project_root_parameter_rewrite.md; git status --short`
inherited_worktree: T031 is ACCEPTED at baseline e75b7fd; README/roadmap/T032 freeze changes are staged; formal companion is present as an untracked frozen input; no unrelated T032 code changes were present before implementation.
fixture_hashes: T031 gold closure manifest=5184e50aeb8c397bea70c8217b35e7d1192b75b3742a6b3cc4ce4875ff3c64b6; T031 eligible/preserved/all digests=0a602a2aa4eee4899707481c927b0620025b0f1561e4ff76dfe0dc780096f6f4 / 33d7a2f06c13d3c9534fa51c7a7134dba9fbffdca737075f0506a864c4905bc3 / 44f893c8cd48d1031236155113e83b89beaed9cb0dc244e2b7a4717aaafde056.
formal_fixture_hashes: child.sv=57e9398d782a9d6efc2f14ecd13f0ef5ace6417d479bc3487f6fe4bafcacb34e (382 B); design.f=b5d10edc287c7f96e0759fef7fb91508742be8bb991214e7ec16ad09bfc7d3f6 (16 B); top.sv=d00624a35124ceea97073a8f12c546c4a741cb47b4cd5c098177e2ddf8c5957e (486 B); input manifest=2fa02a5d1523a1e8d2ebf891f33bf2fa26818c8b9152de3ae23dab53c7537c81; top=t032_top, seq=5.
phase_a: passed. Added parameters as an explicit project-root selection group while keeping the default five groups and the existing 13-group project debug matrix unchanged. Parameter-only source edits are limited to T031 eligible declaration/reference ranges; preserved top and macro ranges are audited but never edited. Mapping v3 validation now accepts a zero-occurrence preserved macro object.
phase_b: passed. T031 gold parameter fixture encrypt summary was exactly `{"files":3,"mapping_entries":7,"modified_tokens":19}`. Mapping selected_groups/categories are `["parameters"]`, closure files are `bus_if.sv, child.sv, top.sv`, entries are 7/19, preserved are DATA_WIDTH(top_parameter), LANES(top_parameter), MACRO_LOCAL(macro_expansion, occurrence 0), strict gate reanalysis is pass with 0/0 diagnostics, and per-file occurrence union equals the 19 global ranges. Input manifest is 5184e50aeb8c397bea70c8217b35e7d1192b75b3742a6b3cc4ce4875ff3c64b6; gate manifest is 1bdf4edb0180acf65e8d855bd211f75551b0b65269fb9377224008aef68a02fc.
phase_c: passed. Combined `signals ports instances struct interface parameters` rewrites successfully with canonical order; omitted category remains the five-group profile. Legacy single-file parameter encrypt/decrypt and filelist v2 workflows remain green. T031/T028 stale pre-T032 rejection assertions were updated to assert the new explicit parameter rewrite contract; no fixture or range oracle was changed.
phase_d: passed. Formal companion gold/gate parameter rewrite returned `{"formal_equivalence":"pass","gate":"/tmp/t032-formal/gate","gold":"tests/formal/t032_project_root_parameters","seq":5,"top":"t032_top"}` with exit 0. A gate-only `~extended_data[...]` functional mutation returned exit 1 and `equiv_status -assert` reported 8 unproven `$equiv` cells; this was a genuine non-equivalence, not a parse failure. Verible and Icarus checks passed (Icarus constant-select warning only).
phase_e: passed. Mapping SHA-256 for the recorded T031 parameter-only run is 23a5941ac72a151e0d2900d5a777bc8d445bf71a454ef0ac92126e01c610132c; metrics SHA-256 is 571f05d364bf160481650fb0cce82aff3d4784f1f806067c65dd2770ac98f61c. Decrypt restored all three closure files byte-identically; concatenated restored-file hash is ca3e345e0a31f733c4403e280262ac4afa846ba16ad999e131b35b5dc3245bfa.
changed_files: rtl_obfuscator/rewrite.py; tests/test_project_root_parameter_rewrite.py; compatibility assertions in tests/test_project_root_parameters.py and tests/test_project_root_rewrite.py; frozen formal companion tests/formal/t032_project_root_parameters/{child.sv,design.f,top.sv}; this task record. Inherited staged README/roadmap changes were not modified by this sub-agent.
exact_commands: `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project.py rtl_obfuscator/inventory.py rtl_obfuscator/rewrite.py tests/test_project_root_parameter_rewrite.py tests/test_project_root_parameters.py tests/test_project_root_rewrite.py`; `conda run -n rtl_obfuscation python -m unittest tests.test_project_root_parameter_rewrite tests.test_project_root_parameters tests.test_project_root_inspect tests.test_project_root_rewrite tests.test_project_root_low_risk -v`; `conda run -n rtl_obfuscation python -m unittest discover -s tests -v`; `conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project --project-root tests/fixtures/t031_project_root_parameters --top parameter_top --output-dir /tmp/t032-parameter.j3SvTt/gate --map /tmp/t032-parameter.j3SvTt/mapping.json --metrics /tmp/t032-parameter.j3SvTt/metrics.json --file-map-dir /tmp/t032-parameter.j3SvTt/maps --category parameters --name-length 8`; `conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project --project-root /tmp/t032-parameter.j3SvTt/gate --top parameter_top --report /tmp/t032-parameter.j3SvTt/gate-report.json --category parameters`; `conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project --gate-dir /tmp/t032-parameter.j3SvTt/gate --map /tmp/t032-parameter.j3SvTt/mapping.json --output-dir /tmp/t032-parameter.j3SvTt/restored`; byte comparison command: `conda run -n rtl_obfuscation python -c 'from pathlib import Path; gold=Path("tests/fixtures/t031_project_root_parameters"); restored=Path("/tmp/t032-parameter.j3SvTt/restored"); assert all((gold/f).read_bytes()==(restored/f).read_bytes() for f in ("bus_if.sv","child.sv","top.sv"))'`; `conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project --project-root tests/formal/t032_project_root_parameters --top t032_top --output-dir /tmp/t032-formal/gate --map /tmp/t032-formal/mapping.json --metrics /tmp/t032-formal/metrics.json --file-map-dir /tmp/t032-formal/maps --category parameters --name-length 8`; `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/formal/t032_project_root_parameters/design.f --gold-root tests/formal/t032_project_root_parameters --gate-filelist /tmp/t032-formal/gate/design.f --gate-root /tmp/t032-formal/gate --top t032_top`; `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/formal/t032_project_root_parameters/design.f --gold-root tests/formal/t032_project_root_parameters --gate-filelist /tmp/t032-formal/negative/design.f --gate-root /tmp/t032-formal/negative --top t032_top`; `conda run -n rtl_obfuscation verible-verilog-syntax tests/formal/t032_project_root_parameters/top.sv`; `conda run -n rtl_obfuscation iverilog -g2012 -t null -s t032_top tests/formal/t032_project_root_parameters/child.sv tests/formal/t032_project_root_parameters/top.sv`; `git diff --check`.
exit_codes: py_compile=0; T032/T031/T027/T028/T030专项=0 (61 tests); full unittest discovery=0 (109 tests); parameter-only encrypt=0; gate inspect=0; decrypt=0; formal positive=0; formal negative=1 with 8 unproven `$equiv`; Verible=0; Icarus=0; git diff --check=0.
mapping_summary: files=3, entries=7, modified_tokens=19; selected_categories=[parameters]; preserved occurrences=16 including zero-range MACRO_LOCAL; renamed names are length 8, unique, legal and disjoint from preserved/original spellings.
metrics_summary: symbols renamed/eligible/coverage=7/7/1.0; occurrences renamed/eligible/coverage=19/19/1.0; effective_coverage=1.0; plaintext_leakage_rate=0.0.
decrypt_hash_comparison: `/tmp/t032-parameter.j3SvTt/restored` matches `tests/fixtures/t031_project_root_parameters` byte-for-byte for bus_if.sv, child.sv and top.sv; restored concatenated hash ca3e345e0a31f733c4403e280262ac4afa846ba16ad999e131b35b5dc3245bfa.
formal_result: PASS; gold=tests/formal/t032_project_root_parameters; gate=/tmp/t032-formal/gate; top=t032_top; command is the exact positive command above; exit_code=0; result JSON reports `formal_equivalence=pass`.
negative_formal_result: command uses the same gold and `/tmp/t032-formal/negative`; exit_code=1; Yosys reaches `equiv_status -assert` and reports 8 unproven `$equiv` cells after the intentional output inversion.
uncovered_boundaries: type parameter, package/class/interface-own parameter declarations, `$unit` parameter, parameter arrays, string/real/struct parameters, defparam, complex hierarchical references and macro identifiers without physical source locations remain unsupported or preserved per T031. T033/RISC-V-Vector parameter integration and default-profile promotion remain out of scope.
status_action: changed status to `READY_FOR_REVIEW`; did not set `ACCEPTED`, commit, or push.
```

## 12. 主 Agent 验收结果

主 Agent 已独立重跑并通过全部 T032 门禁：

```text
target_unittest: PASS; 61 tests, OK
full_unittest: PASS; 109 tests, OK
py_compile: PASS; exit 0
parameter_only_encrypt: PASS; {"files":3,"mapping_entries":7,"modified_tokens":19}
gate_reanalysis: PASS; status=pass, parse_errors=0, semantic_errors=0, eligible=7/19
mapping_metrics: PASS; version=3, mapping_entries=7, preserved=3, symbol_coverage=1.0, occurrence_coverage=1.0, effective_coverage=1.0, plaintext_leakage_rate=0.0
decrypt: PASS; bus_if.sv, child.sv and top.sv byte-identical to T031 gold
formal_positive: PASS; exit 0; {"formal_equivalence":"pass","seq":5,"top":"t032_top"}
formal_negative: PASS; exit 1; Yosys reached equiv_status -assert and reported 8 unproven $equiv cells after intentional output inversion
verible: PASS; exit 0
iverilog: PASS; exit 0; constant-select warning only
git_diff_check: PASS
fixed_inputs: PASS; T031 gold/negative fixture and range digest unchanged; formal companion hashes unchanged
formal_verification: PASS
acceptance: ACCEPTED
status_action: Main Agent set T032 to ACCEPTED; no commit or push performed
```
