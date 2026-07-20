# T033：Impact/category oracle 与统一 profile registry

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T032 `ACCEPTED`
- 计划文档：[`docs/category_profile_normalization_plan.md`](../category_profile_normalization_plan.md)
- Formal verification：`N/A`（本任务只生成 impact/category inventory 和 source-range oracle，不改写 RTL）

## 1. 单一目标

在不改变现有 gate、mapping v1/v2/v3 和历史任务 oracle 的前提下，建立可复用的
`single_module` / `multi_module` / `top_abi` 分类和共享 category registry，为 T034/T035 的
单文件、filelist、project-root profile 迁移冻结机器可检查的输入与输出。

T033 不生成 rewritten RTL，不改变默认加密行为，不实现 mapping v4，不实现 filelist 拒绝
multi-module category；这些属于 T034/T035。

## 2. 强制行为规范

子 Agent 开始前必须：

1. 阅读 `AGENTS.md`、`docs/tasks/README.md`、本任务、T027–T032、计划文档和 formal 说明；
2. 确认没有其他 `IN_PROGRESS` 或 `READY_FOR_REVIEW` 任务；
3. 将本文件从 `READY` 改为 `IN_PROGRESS`，填写 HEAD、开始时间、fixture hash 和首条命令；
4. 只修改“允许修改的文件”；
5. 所有 Python、PySlang、Verible、Icarus 和测试命令使用 `conda run -n rtl_obfuscation`；
6. 不修改 T030/T031/T032 fixture、历史 mapping、旧 formal 输入或历史任务证据；
7. 不 commit、push、设置 `ACCEPTED` 或创建 T034/T035；
8. 发现无法确认 owner、category ownership 或 parameter override binding 时，记录偏差并
   fail-closed，不得文本扫描补救；
9. 完成后记录 exact commands、exit codes、oracle digest、未覆盖边界，并设置
   `READY_FOR_REVIEW`。

## 3. 固定输入

```text
tests/fixtures/t033_impact_category/
├── design.f
├── bus_if.sv
├── shared.sv
├── child.sv
├── top.sv
└── decoy.sv
```

固定 filelist 顺序：`bus_if.sv`, `shared.sv`, `child.sv`, `top.sv`, `decoy.sv`。
固定 top：`t033_top`。

固定文件 SHA-256：

```text
bus_if.sv  84 bytes    65b5eed23d7e42034efb49eda5cb0bc14b423b4254e195dfdc0890ecf37c084c
child.sv   1193 bytes  cf0354d17b9e6403cf10c4c09550bf5def012ba71a74e06e08e4dcbac96f6a30
decoy.sv   91 bytes    c49bd9ff96216424b5b72cd7fbed31ee335a1f0d2fbc7931b9c9bbba9c89aa51
shared.sv  89 bytes    5138529e590b0e3752b6a26964c9dcb5448e2a2b179f9d693e06200699700cf4
top.sv     457 bytes   c5fd4c5cbdc37509e3a069d1c50ac581e08af6f9253c231341e3fa400cc59dce
manifest: 07ca8b3be018cabfc14ce118791c7a8db8cbcb0618d3d243ad413de6c5e0aeea
```

通过 `inspect-project` 的共享 SourceManager/closure 基线必须为：`candidate_files=5`、
`closure_files=4`、`definitions=4`、reachable modules `t033_child,t033_top`、reachable interface
`t033_bus_if`、`parse_errors=0`、`semantic_errors=0`。每个 category 的单独 inspect 必须
通过；当前把 `ports` 与 `interface` 合并会暴露预期的 duplicate-range ownership 缺口，T033
必须修复分类 ownership 后再生成 combined classification。`decoy.sv` 只在 candidate files，
不得进入 project-root closure 或 project-root classification。

Verible 对五个 `.sv` 文件必须退出 0。Icarus 当前对 child 的 interface-port 语法退出 2，
该结果是已知前端边界，只能记录为附加证据，不能作为 T033 的语义来源或 formal 证据。

## 4. Impact/category oracle

每条记录的 key 为 `(category, scope, name)`；`occurrences` 包含 declaration 和所有
source-validated references。T033 必须输出与下面完全一致的 category、scope、name、impact、
abi 和 occurrence 数量。

### 4.1 默认 single-module/internal

```text
signals/t033_child: child_signal(5), child_state(2), child_value(1), child_union(2), child_word(3), shared_value(2)
signals/t033_top:   top_signal(2), top_shared(2)
instances/t033_top: u_child(1)
struct_fields/t033_child: field(1)
struct_types/t033_child: child_t(2), child_union_t(2)
enum_values/t033_child: CHILD_IDLE(1), CHILD_BUSY(2)
genvars/t033_child: child_index(3)
functions/t033_child: child_fn(2)
tasks/t033_child: child_task(1)
arguments/t033_child: value(2), value(2)  # two distinct formal symbols
generate_blocks/t033_child: child_generate(1)
typedefs/t033_child: child_word_t(2)
union_fields/t033_child: raw(2), lane(1)
parameters/t033_child: CHILD_LOCAL(1)
parameters/t033_top: TOP_LOCAL(1)
```

Expected default oracle totals: **25 symbols / 46 occurrences**. The two `arguments/value`
entries must remain distinct by declaration range and must not be merged by spelling.

### 4.2 Multi-module or ABI/manual project-root

```text
modules/t033_child: t033_child(2)                   # child declaration + top instance type
ports/t033_child: data(3), q(3)                         # ordinary module ports only
interfaces/$unit: t033_bus_if(3)
interface_instances/t033_top: bus(3)                   # declaration + RHS/base uses in top
interface_ports/t033_child: bus(3)                     # interface port declaration + child/connection uses
interface_ports/t033_bus_if: valid(4)
modports/t033_bus_if: sink(1)
parameters/t033_child: WIDTH(9)                      # named override in t033_top
struct_types/$unit: t033_shared_t(3)                 # shared compilation-unit type
struct_fields/$unit::t033_shared_t: valid(3), payload(1)
```

Expected manual multi-module oracle totals: **12 symbols / 38 occurrences**. `modules` is a
reserved manual category for T035; T033 must still classify its declaration/type ranges without
rewriting them.

### 4.3 Top ABI preserved

```text
modules/t033_top: t033_top(1), reason=top_module
ports/t033_top: data(3), q(2), reason=top_port
parameters/t033_top: TOP_WIDTH(6), reason=top_parameter
```

Expected top ABI totals: **4 symbols / 12 occurrences**. Their `impact` may be
`single_module`, but `abi=top_abi` and they are never default eligible.

### 4.4 Ownership invariant

No physical range may occur in two category records. In particular, the interface port connection
range for `bus` must not be emitted simultaneously under ordinary `ports` and
`interface_instances`; it belongs to `interface_ports/t033_child`, while the top interface instance
belongs to `interface_instances/t033_top`. A combined profile with duplicate ranges is a T033 failure.

## 5. Deterministic digests

For each category, normalize records using fields
`category/scope/name/declaration/references/occurrences`, sort by
`(category,scope,declaration.file,declaration.start,name)`, serialize with
`json.dumps(sort_keys=True,separators=(",",":"),ensure_ascii=False)`, then SHA-256.

The pre-classification source-range oracle digests are frozen as follows. T033 must keep these raw
category/range digests stable for compatibility; any disjoint ownership reassignment is represented
only in the new classification section and is consumed by T034/T035.

```text
signals         8 symbols / 19 occurrences  130583698415fd3ea8ae4f1acde19a50b048bd8e132ac8fcc9138a4aa118bd72
ports           5 symbols / 15 occurrences  10dfd9143df6ed02ab6d016237ac301e9693523c920bc680d171023623e750fe
instances       1 symbol  / 1 occurrence    70f0ab215e2f317e7607fbc7d7adc57479435231890d7db0fe3df441e077326c
struct          6 symbols / 12 occurrences  e74de69c66a5b29f3f662d36a14e33549c48e849d145ef08c4309ca427b9beb2
interface       4 symbols / 12 occurrences  535c43fa758201bc76c4d7f88be6b74a5dcdc6cf95753c369235e5fd1bd50e26
parameters      4 symbols / 17 occurrences  0cbd6fc883f50a616d6f04dcdd696f13978d0489318b3c35cee8ab63da915222
enum_values     2 symbols / 3 occurrences   a919b7a7c9847f8c38ee27f504ac1c24821a0150aeae02f13a94e8cf713016ef
genvars         1 symbol  / 3 occurrences   0b5b37efef2d0d44b40f5cf7cb40318230f49659f7857c81470a5258fa681941
functions       1 symbol  / 2 occurrences   84e2fe0f9aad064449ae9fd1aca1e2e7277446742e2d386a6c9058bbc2fbb184
tasks           1 symbol  / 1 occurrence    c978d61712bae393acaa3739dd306ad6968f8df7eb171791908c47c5b57b81e3
arguments       2 symbols / 4 occurrences   0a92bd75409260d7e87882265a2c73d8f1a954e6567e77818462705779466078
generate_blocks 1 symbol  / 1 occurrence    47b3cd7207a52b87b369e4184cc64b583693de8d8b6054265d30792d753792f1
typedefs        1 symbol  / 2 occurrences   8a69afedcaa17286a033536282d607f158917e7c30bc4cc230af61733fbc178b
union_fields    2 symbols / 3 occurrences   0ca545b00c188926b7485dbf6535d37d57dcd4a7350f5e0c5c9a4a89909b917d
combined        39 symbols / 95 occurrences 1988aa06350cff1e4cb4a23cccb4a8734f513cabd666b56f8bddcc3b56bc1395
```

## 6. Expected classification report

T033 应在 inspect report 中增加独立的 classification/profile section，而不是修改现有
eligible/preserved entry schema，以保持 T027–T032 digest 兼容。最小结构为：

```json
{
  "classification": {
    "default_profile": {"entries": 25, "occurrences": 46},
    "manual_multi_module": {"entries": 12, "occurrences": 38},
    "top_abi_preserved": {"entries": 4, "occurrences": 12},
    "unreachable": ["decoy.sv"]
  }
}
```

每个 classification entry 必须包含 `category`, `scope`, `name`, `impact`, `abi`,
`default_eligible`, `project_root_manual`, `declaration`, `references`, `occurrences`。

## 7. 允许修改的文件

- `rtl_obfuscator/inventory.py`：owner/module-set 计算、range ownership 和 classification；
- `rtl_obfuscator/project.py`：共享 registry 接口和 inspect report classification section；
- `rtl_obfuscator/rewrite.py`：只接入 registry 元数据，不改变 T032 rewrite/profile 行为；
- `tests/test_t033_impact_category.py`：T033 black-box oracle tests；
- `tests/fixtures/t033_impact_category/**`：仅允许修复 fixture 使冻结 hash/语义成立；
- 本任务单的执行记录。

禁止修改 T030/T031/T032 fixture、旧 mapping validator、默认加密输出、FIFO/RISC-V-Vector
fixture、formal script、README 和已验收任务证据。

## 8. 验收命令

```sh
conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/inventory.py rtl_obfuscator/project.py rtl_obfuscator/rewrite.py \
  tests/test_t033_impact_category.py

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t033_impact_category \
  tests.test_project_root_inspect \
  tests.test_project_root_parameters \
  tests.test_project_root_low_risk -v

conda run -n rtl_obfuscation python -m unittest discover -s tests -v
git diff --check
```

必须程序化断言：fixture manifest、closure、所有 category digest、classification totals、
range bytes、determinism、unreachable exclusion、ownership disjointness 和 legacy tests。

Formal verification：

```text
formal_verification: N/A
reason: T033 produces only classification/source-range inventory; no rewritten RTL is produced.
```

## 9. READY → READY_FOR_REVIEW 门禁

只有以下全部满足时才能申请 review：

1. 状态从 `READY` 正确更新为 `IN_PROGRESS` 并记录执行证据；
2. fixture manifest 和 source-range digests 与本合同一致；
3. default/manual/top-ABI totals 与 oracle 一致；
4. interface/port ranges 无 duplicate/overlap；
5. `decoy.sv` 不进入 project-root closure/classification；
6. 专项测试、完整回归、py_compile 和 git diff check 通过；
7. Formal 按上述格式记录 `N/A`；
8. 未设置 `ACCEPTED`、未 commit、未 push。

## 10. 执行记录

子 Agent 开始后填写：

```text
start_time: 2026-07-20 14:53:13 CST
head: e7bc0947e7c5ffe11960147f6f5cf552cef1b4c3
first_command: `sed -n '1,260p' docs/tasks/README.md; sed -n '1,460p' docs/tasks/T033_impact_category_oracle.md; git status --short`
inherited_worktree: T032 and earlier tasks are accepted; T033 plan, task contract, and fixture are present as inherited uncommitted worktree changes; no other task is IN_PROGRESS or READY_FOR_REVIEW.
fixture_manifest: PASS; candidate `.sv` manifest `07ca8b3be018cabfc14ce118791c7a8db8cbcb0618d3d243ad413de6c5e0aeea`; closure manifest `e9bca1f5787aadfe515f0b06ecb54149f536dd4ca0e6297dab1f142aea9baf9a`; fixed file sizes/SHA-256 match the contract
changed_files: `rtl_obfuscator/inventory.py`, `rtl_obfuscator/project.py`, `tests/test_t033_impact_category.py`, `tests/fixtures/t033_impact_category/{design.f,bus_if.sv,shared.sv,child.sv,top.sv,decoy.sv}`, this task record; inherited unrelated worktree changes in `docs/future_work.md`, `docs/project_root_parameter_plan_draft.md`, and `docs/project_root_top_roadmap.md` were preserved
exact_commands:
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/inventory.py rtl_obfuscator/project.py rtl_obfuscator/rewrite.py tests/test_t033_impact_category.py`
  - `conda run -n rtl_obfuscation python -m unittest tests.test_t033_impact_category tests.test_project_root_inspect tests.test_project_root_parameters tests.test_project_root_low_risk -v`
  - `conda run -n rtl_obfuscation python -m unittest discover -s tests -v`
  - `for f in tests/fixtures/t033_impact_category/*.sv; do conda run -n rtl_obfuscation verible-verilog-syntax "$f" >/dev/null; code=$?; printf '%s exit=%s\\n' "$f" "$code"; done`
  - `conda run -n rtl_obfuscation iverilog -g2012 -t null -s t033_child tests/fixtures/t033_impact_category/bus_if.sv tests/fixtures/t033_impact_category/shared.sv tests/fixtures/t033_impact_category/child.sv`
  - `git diff --check`
exit_codes: py_compile=0; targeted unittest=0; full unittest=0; Verible all five files=0; Icarus child interface-port known boundary=2; git diff --check=0
classification_summary: PASS; candidate_files=5; closure_files=4; definitions=4; reachable modules=`t033_child,t033_top`; reachable interface=`t033_bus_if`; parse_errors=0; semantic_errors=0; default_profile=25/46; manual_multi_module=12/38; top_abi_preserved=4/12; unreachable=`decoy.sv`
oracle_digest: PASS; all frozen raw category digests, totals, and combined digest `1988aa06350cff1e4cb4a23cccb4a8734f513cabd666b56f8bddcc3b56bc1395` (39 symbols / 95 occurrences) pass, with deterministic reports
ownership_check: PASS; all classification ranges are byte-validated and disjoint; the child formal `.bus` connection is owned by `interface_ports/t033_child`, while top `bus` uses remain under `interface_instances/t033_top`
full_unittest: PASS; `Ran 113 tests in 577.061s`, `OK`
py_compile: PASS; exit code 0
git_diff_check: PASS; exit code 0
formal_verification: N/A
reason: T033 produces only classification/source-range inventory; no rewritten RTL is produced.
uncovered_boundaries: Icarus does not parse the fixture's interface-port syntax (known exit 2); Verible and PySlang/shared SourceManager checks are the applicable syntax/semantic evidence. No RTL rewrite or Yosys equivalence applies.
```

## 11. 主 Agent 验收记录

acceptance_time: 2026-07-20 16:34:00 CST
acceptance_head: e7bc0947e7c5ffe11960147f6f5cf552cef1b4c3
acceptance_commands:
  - `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/inventory.py rtl_obfuscator/project.py rtl_obfuscator/rewrite.py tests/test_t033_impact_category.py`
  - `conda run -n rtl_obfuscation python -m unittest tests.test_t033_impact_category tests.test_project_root_inspect tests.test_project_root_parameters tests.test_project_root_low_risk -v`
  - `conda run -n rtl_obfuscation python -m unittest discover -s tests -v`
  - `git diff --check`
  - `for f in tests/fixtures/t033_impact_category/*.sv; do conda run -n rtl_obfuscation verible-verilog-syntax "$f" >/dev/null || exit $?; done`
acceptance_results: py_compile=PASS; targeted unittest=`Ran 42 tests in 62.319s`, `OK`; full unittest=`Ran 113 tests in 665.080s`, `OK`; git_diff_check=PASS; Verible five fixtures=PASS
formal_verification: N/A
formal_reason: T033 produces only classification/source-range inventory; no rewritten RTL is produced.
acceptance_conclusion: PASS; T033 is accepted by the Main Agent. The known Icarus exit 2 for the interface-port fixture remains an inherited frontend boundary and is not used as T033 semantic or formal evidence.
