# T031：`project-root + top` Parameter inventory 与 source ranges

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T030 `ACCEPTED`
- 计划基线：`1d6788b`；T030 acceptance bundle 已由主 Agent 暂存，子 Agent 开始前必须确认其已提交或作为继承工作区明确记录
- Formal verification：`N/A`（本任务只生成 inventory/source-range，不改写 RTL）
- 关联计划归档：[`docs/project_root_parameter_plan_draft.md`](../project_root_parameter_plan_draft.md)

## 1. 单一目标

在现有 `project-root + top` 语义闭包中增加显式 `parameters` 用户选择项，并为 module-scoped value parameter/localparam 建立可审计的声明和引用范围。

T031 不生成 gate，不修改 RTL，不改变当前默认五组 profile。完成后应能运行：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root <fixture-root> \
  --top parameter_top \
  --report /tmp/t031-parameter-report.json \
  --category parameters
```

## 2. 子 Agent 行为规范

开始前必须完整阅读 `AGENTS.md`、`docs/tasks/README.md`、parameter 草案、T027/T028/T029/T030 任务单、`docs/formal_verification.md`、`docs/systemverilog_renaming_table.md` 和 `docs/project_root_top_roadmap.md`。

然后依次执行：

1. 确认没有其他任务处于 `IN_PROGRESS` 或 `READY_FOR_REVIEW`；
2. 确认 T031 是唯一待执行任务；
3. 本合同当前已冻结为 `READY`；子 Agent 开始前把本文件从 `READY` 改为 `IN_PROGRESS`；
4. 在执行记录写明开始时间、HEAD、首条命令、继承的工作区状态和 fixture hash；
5. 严格按 Phase A → B → C → D 执行，前一阶段失败时停止后续阶段；
6. 只修改“允许修改文件”列出的文件；
7. 所有 Python、PySlang、Verible、Icarus 和测试命令使用 `conda run -n rtl_obfuscation`；
8. 不得修改现有 FIFO、RISC-V-Vector、T027/T030 fixture、旧 formal input 或既有 oracle；
9. 不得 commit、push、设置 `ACCEPTED` 或创建 T032/T033；
10. 完成后记录 exact command、exit code、JSON、range digest、未覆盖边界，并把状态改为 `READY_FOR_REVIEW`。

若遇到 API 差异、无法确认 symbol identity、需要扩展到 package/class/interface parameter，必须写入“偏差或阻塞”，保持 `IN_PROGRESS` 或 `BLOCKED`，不能用文本扫描或放宽审计继续。

## 3. 功能范围

### 3.1 允许进入 inventory

- module-scoped value parameter；
- module-scoped `localparam`；
- reachable 非 top module 的 parameter/localparam：`eligible`；
- top module value parameter：`preserved(reason="top_parameter")`；
- macro-generated parameter-like object：`preserved(reason="macro_expansion")`。

### 3.2 必须发现的引用

引用必须按 symbol identity 绑定并做源 bytes 校验：

1. 普通 constant expression；
2. localparam RHS，例如 `DATA_WIDTH + 8`；
3. signal/port dimensions；
4. procedural loop bound 和 constant expression；
5. generate-for 初始化、终止、步进表达式；
6. generate-if/conditional generate 条件；
7. struct field dimension；
8. reachable interface member dimension；
9. module named parameter override 左侧；
10. named override RHS 中对 parent parameter 的引用；
11. interface instance override RHS 中对 module parameter 的引用。

### 3.3 明确不包含

- type parameter；
- package/class/interface 自身的 parameter declaration；
- `$unit` parameter；
- parameter array、string、real 等复杂 parameter；
- `defparam`、复杂 hierarchical reference；
- struct 作为 parameter 类型；
- 按文本名称替换或 macro 无法定位的 physical identifier；
- T032 的 rewritten RTL、mapping entry、decrypt、formal equivalence。

不支持输入必须返回稳定诊断或明确 preserved reason，不能静默进入 eligible。

## 4. 固定 fixture 设计

主 Agent 已冻结以下输入。子 Agent 只能读取冻结内容，不得修改：

```text
tests/fixtures/t031_project_root_parameters/
├── design.f
├── child.sv
├── bus_if.sv
└── top.sv
```

固定 top：`parameter_top`。

fixture 必须包含：

- top value parameters，其中至少一个必须 preserved；
- top localparam，其中至少一个可 eligible；
- child value parameter/localparam；
- `DATA_WIDTH + 8`、除法或其他简单 integral expression；
- port/signal packed dimension；
- procedural loop；
- generate-for 和 generate-if；
- module named override；
- struct field dimension；
- interface member/override 对参数的引用；
- 同文件 unreachable module，包含同名 parameter；
- macro-generated parameter-like declaration，必须 preserved；
- 至少一个 local signal/genvar shadowing case；
- 不修改旧 T030 fixture。

固定正例 hash：

```text
bus_if.sv  119 bytes  3fb78fcb5fc61ffd2f5b6c4c9d39ad6bf340e752938926324226cb89e0ef5695
child.sv   744 bytes  9c0caa0b35d4f944d55792e222ea66563865329a4184a4c50bda1d7dbf90f6d8
design.f    26 bytes  c1fb8a7808f3d2886edadeb96d03b73e0bbca88fbde203853d36f2cb7d96e4c9
top.sv    1413 bytes  278843d4a4070f8a27169667d89b19b148223352b4018cf6c0077626434b1623
manifest: 8239fcaf22471c1606fa47dce2098c5b1286bd7c6db8208584a03a5d4ef7f599
```

固定负例：`tests/fixtures/t031_project_root_parameters_negative/`，包含一个 `parameter type`，预期诊断 code 为 `UNSUPPORTED_PARAMETER_KIND`，不得生成成功 inventory：

```text
design.f  7 bytes    4f88f88837c0f8df8ea76f4b740391ac9daa8892bf35e41871dc15c284d3cef1
top.sv  147 bytes  7aa1a3f77cff590542a93637913d2f6c77f755ca22cfa0dc68ae1023532403c0
manifest: d95fff5b00bbed7f11de4db0495d050239efdd685afef43e95361f9e15d6209e
```

冻结前输入检查：PySlang syntax errors `0`、semantic errors `0`；Verible syntax exit `0`；Icarus `-g2012 -t null -s parameter_top -c design.f` exit `0`（仅报告 constant-select warning）。

正例固定 closure：`candidate_files=3`、`closure_files=3`、`definitions=4`、`reachable.modules=["parameter_child","parameter_top"]`、`reachable.interfaces=["bus_if"]`、`parse_errors=0`、`semantic_errors=0`。`unreachable_parameter_decoy` 只存在于 definitions，不得进入 reachable 或 parameter inventory。

固定 module-scoped parameter oracle：

| scope | name | classification | declaration | references | occurrences |
| --- | --- | --- | --- | --- | ---: |
| `parameter_child` | `WIDTH` | eligible | `child.sv:44-49` | `child.sv:105-110,142-147,196-201,222-227; top.sv:752-757` | 6 |
| `parameter_child` | `DEPTH` | eligible | `child.sv:73-78` | `child.sv:204-209,392-397; top.sv:780-785` | 4 |
| `parameter_child` | `CHILD_SUM_W` | eligible | `child.sv:182-193` | `child.sv:256-267` | 2 |
| `parameter_top` | `DATA_WIDTH` | preserved(`top_parameter`) | `top.sv:116-126` | `top.sv:193-203,230-240,272-282,333-343,425-435,499-509,612-622,649-659,695-705,758-768,1047-1057,1309-1319` | 13 |
| `parameter_top` | `LANES` | preserved(`top_parameter`) | `top.sv:151-156` | `top.sv:1139-1144,1258-1263` | 3 |
| `parameter_top` | `TOP_LOCAL` | eligible | `top.sv:181-190` | none | 1 |
| `parameter_top` | `PARTIAL_SUM_W` | eligible | `top.sv:317-330` | `top.sv:539-552` | 2 |
| `parameter_top` | `DIV_CALC_CYCLES` | eligible | `top.sv:368-383` | `top.sv:438-453` | 2 |
| `parameter_top` | `DIV_BIT_GROUPS` | eligible | `top.sv:408-422` | `top.sv:786-800` | 2 |
| `parameter_top` | `MACRO_LOCAL` | preserved(`macro_expansion`) | none | none | 0 |

固定 summary：

```text
selected module-scoped symbols: 10
eligible symbols/occurrences: 7 / 19
preserved symbols/occurrences: 3 / 16
all symbols/occurrences: 10 / 35
eligible digest: 0a602a2aa4eee4899707481c927b0620025b0f1561e4ff76dfe0dc780096f6f4
preserved digest: 33d7a2f06c13d3c9534fa51c7a7134dba9fbffdca737075f0506a864c4905bc3
all digest: 44f893c8cd48d1031236155113e83b89beaed9cb0dc244e2b7a4717aaafde056
```

digest 输入为按 `(category, scope, declaration.file, declaration.start, original_name)` 排序的 entry，保留 `category/scope/original_name/declaration/references/occurrences` 字段，使用 `json.dumps(sort_keys=True, separators=(",", ":"))` 后 SHA-256。interface 自身的 `WIDTH` 只用于 interface member/override 语法存在性；T031 module-scoped parameter inventory 不对其改名。

## 5. CLI 与 inventory 合同

### 5.1 Category selection

允许：

```text
--category parameters
```

省略 `--category` 时仍为既有五组：

```text
signals ports instances struct interface
```

T031 不得把 parameters 加入默认 profile，也不得改变 T027/T028/T029/T030 oracle。

### 5.2 Canonical order

`parameters` 是独立用户 group，实际 category 为 `parameters`。重复参数不得产生重复 category；canonical JSON 顺序必须稳定，与用户传参顺序无关。

### 5.3 Inventory schema

现有 report schema 保持不变：

```json
{
  "inventory": {
    "eligible": [],
    "preserved": [],
    "unsupported": []
  }
}
```

每个 eligible/preserved entry 必须包含现有字段：`category, scope, name, declaration, references, occurrences, reason`。

每个 range 必须满足：file 相对于 project-root、start/end 精确覆盖原 identifier、declaration 不与 reference 重复、同一 entry 无重复或重叠 ranges、不可达 module 不进入 inventory。

## 6. 允许修改的文件和代码边界

允许的最小范围：

- `rtl_obfuscator/inventory.py`：reachable parameter collector、reference helpers、range audit；
- `rtl_obfuscator/project.py`：`parameters` group、validation、deterministic expansion；
- `rtl_obfuscator/rewrite.py`：inspect-project 的 `parameters` choice 和 project-root selection 元数据，不接通 encrypt rewrite；
- `tests/test_project_root_parameters.py`：T031 black-box inventory tests；
- `tests/fixtures/t031_project_root_parameters/**`：冻结 fixture；
- 本任务单和 parameter 草案的执行记录。

禁止修改既有 RTL fixture、RISC-V-Vector、example FIFO、T032 rewrite/decrypt、formal scripts 或旧任务 oracle。

## 7. 分阶段执行和门禁

### Phase A：API probe 与边界冻结

确认 PySlang 实际暴露的 parameter/localparam `SymbolKind`、`isType`、`declaringDefinition`、localparam RHS NamedValue、generate-for/generate-if semantic nodes、struct/interface dimension nodes、named override syntax、macro location 和 source manager fallback。输出最小 probe 命令、实际 API 属性、fixture hash、未支持 API 清单；失败则停止，不写文本 fallback。

### Phase B：只读 inventory

必须通过 parameters-only inspect、existing groups + parameters inspect、重复运行 report SHA-256 一致、unreachable 不出现、top parameter preserved、macro object preserved、所有 ranges source bytes exact、shadowing 不串绑、unsupported negative 稳定失败或明确 preserved。

### Phase C：回归兼容

必须证明省略 category 的五组结果不变，T027/T028/T029/T030 测试和 oracle 不变，legacy filelist/single-file parameter behavior 不变，parameters-only 不产生 rewritten RTL。

### Phase D：交付记录

记录 changed files、exact commands、exit codes、range digest、完整测试摘要、formal `N/A` 及原因、未覆盖边界，并设置 `READY_FOR_REVIEW`。

## 8. 固定验收命令模板

主 Agent 冻结 fixture 后，必须把 `<...>` 替换为固定值并写回本合同。

### 8.1 编译和测试

```sh
conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project.py rtl_obfuscator/inventory.py \
  rtl_obfuscator/rewrite.py tests/test_project_root_parameters.py

conda run -n rtl_obfuscation python -m unittest \
  tests.test_project_root_parameters \
  tests.test_project_root_inspect \
  tests.test_project_root_rewrite \
  tests.test_project_root_low_risk -v

conda run -n rtl_obfuscation python -m unittest discover -s tests -v
```

### 8.2 Deterministic inspect

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root tests/fixtures/t031_project_root_parameters \
  --top parameter_top \
  --report /tmp/t031-parameters-a.json \
  --category parameters

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root tests/fixtures/t031_project_root_parameters \
  --top parameter_top \
  --report /tmp/t031-parameters-b.json \
  --category parameters

conda run -n rtl_obfuscation python -c 'from pathlib import Path; import hashlib; a=Path("/tmp/t031-parameters-a.json").read_bytes(); b=Path("/tmp/t031-parameters-b.json").read_bytes(); assert a==b; print(hashlib.sha256(a).hexdigest())'
```

### 8.3 Syntax checks

```sh
conda run -n rtl_obfuscation verible-verilog-syntax tests/fixtures/t031_project_root_parameters/top.sv
conda run -n rtl_obfuscation iverilog -g2012 -t null \
  -s parameter_top \
  tests/fixtures/t031_project_root_parameters/bus_if.sv \
  tests/fixtures/t031_project_root_parameters/child.sv \
  tests/fixtures/t031_project_root_parameters/top.sv
```

T031 不运行 `scripts/formal_equivalence.py`，不得把 identity parse 当作 formal evidence。

## 9. READY_FOR_REVIEW 门禁

子 Agent 只有同时满足以下条件才能申请 review：

1. 状态已从 `READY` 变为 `IN_PROGRESS`，执行记录完整；
2. 只修改允许文件；
3. parameters-only inventory oracle 全部通过；
4. range digest、fixture hash、determinism 通过；
5. top parameter、macro、unreachable、shadowing 和 unsupported 边界有证据；
6. T027/T028/T029/T030 既有测试和完整回归通过；
7. formal verification 明确记录 `N/A`；
8. 记录所有未覆盖边界；
9. 状态改为 `READY_FOR_REVIEW`，不得设置 `ACCEPTED`。

以下任一情况必须保持 `IN_PROGRESS` 或 `BLOCKED`：文本名称扫描、range 无法精确回读、不可达对象进入 eligible、top parameter 进入 eligible、unsupported parameter 被静默忽略、默认五组 oracle 改变、测试被删除/放宽/跳过。

## 10. Formal verification 记录

```text
formal_verification: N/A
reason: no rewritten RTL is produced by T031; T032 owns encrypt/gate formal verification
```

## 11. 执行记录

主 Agent 在设置 `READY` 前填写冻结基线。子 Agent 开始后填写：

```text
start_time: 2026-07-20 11:27:34 CST
head: 1d6788b
first_command: `sed -n '1,240p' docs/tasks/README.md; find docs/tasks -maxdepth 1 -type f -print | sort | rg 'T031|README'`
inherited_worktree: T030 acceptance bundle and T031 plan/fixtures are staged at baseline 1d6788b; no unrelated unstaged changes were present at start
fixture_hashes: positive bus_if.sv=3fb78fcb5fc61ffd2f5b6c4c9d39ad6bf340e752938926324226cb89e0ef5695 (119 B), child.sv=9c0caa0b35d4f944d55792e222ea66563865329a4184a4c50bda1d7dbf90f6d8 (744 B), design.f=c1fb8a7808f3d2886edadeb96d03b73e0bbca88fbde203853d36f2cb7d96e4c9 (26 B), top.sv=278843d4a4070f8a27169667d89b19b148223352b4018cf6c0077626434b1623 (1413 B); negative design.f=4f88f88837c0f8df8ea76f4b740391ac9daa8892bf35e41871dc15c284d3cef1 (7 B), top.sv=7aa1a3f77cff590542a93637913d2f6c77f755ca22cfa0dc68ae1023532403c0 (147 B)
phase_a: passed. PySlang probe confirmed module-scoped value/localparam symbols, declaration ownership, NamedValue and dimension/generate/named-override reference nodes, and macro source locations; no text-scan fallback was added. Fixed positive/negative fixture hashes and closure compilation matched the contract (parse_errors=0, semantic_errors=0).
phase_b: passed. parameters-only inspect returned candidate_files=3, closure_files=3, definitions=4, reachable.modules=[parameter_child, parameter_top], reachable.interfaces=[bus_if], eligible=7 symbols/19 occurrences, preserved=3 symbols/16 occurrences. Top parameters are preserved with top_parameter, macro-generated MACRO_LOCAL is preserved with macro_expansion and no declaration, unreachable_parameter_decoy is absent, ranges read back exact source bytes, and repeated reports are byte-identical (report SHA-256 936d1159e8436a4215b499fc5722f77c8929afdd4cff886132dcad5bf1ae1b51).
phase_c: passed. T031 + T027/T028/T030专项 suite ran 56 tests with OK; full unittest discovery ran 104 tests with OK. Default project profile remains five groups, legacy single-file parameters encrypt/decrypt remains available, project-root parameters encrypt is rejected before output creation, and unsupported type parameter fails closed with UNSUPPORTED_PARAMETER_KIND.
phase_d: passed. Deterministic inspect, Verible syntax, Icarus compilation (constant-select warning only), py_compile, and git diff --check all passed; no RTL rewrite or formal flow was produced.
changed_files: rtl_obfuscator/inventory.py; rtl_obfuscator/project.py; rtl_obfuscator/rewrite.py; tests/test_project_root_parameters.py; tests/fixtures/t031_project_root_parameters/{bus_if.sv,child.sv,design.f,top.sv}; tests/fixtures/t031_project_root_parameters_negative/{design.f,top.sv}; this task record.
exact_commands: `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project.py rtl_obfuscator/inventory.py rtl_obfuscator/rewrite.py tests/test_project_root_parameters.py`; `conda run -n rtl_obfuscation python -m unittest tests.test_project_root_parameters tests.test_project_root_inspect tests.test_project_root_rewrite tests.test_project_root_low_risk -v`; `conda run -n rtl_obfuscation python -m unittest discover -s tests -v`; `conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project --project-root tests/fixtures/t031_project_root_parameters --top parameter_top --report /tmp/t031-parameters-a.json --category parameters`; same command with `/tmp/t031-parameters-b.json`; `conda run -n rtl_obfuscation python -c 'from pathlib import Path; import hashlib; a=Path("/tmp/t031-parameters-a.json").read_bytes(); b=Path("/tmp/t031-parameters-b.json").read_bytes(); assert a==b; print(hashlib.sha256(a).hexdigest())'`; `conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project --project-root tests/fixtures/t031_project_root_parameters_negative --top parameter_type_negative --report /tmp/t031-negative.json --category parameters`; `conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project --project-root tests/fixtures/t031_project_root_parameters --top parameter_top --output-dir /tmp/t031-gate --map /tmp/t031-map.json --metrics /tmp/t031-metrics.json --category parameters --name-length 8`; `conda run -n rtl_obfuscation verible-verilog-syntax tests/fixtures/t031_project_root_parameters/top.sv`; `conda run -n rtl_obfuscation iverilog -g2012 -t null -s parameter_top tests/fixtures/t031_project_root_parameters/bus_if.sv tests/fixtures/t031_project_root_parameters/child.sv tests/fixtures/t031_project_root_parameters/top.sv`; `git diff --check`.
exit_codes: py_compile=0;专项 unittest=0 (56/56); full unittest=0 (104/104); inspect A=0, inspect B=0, deterministic hash=0; Verible=0; Icarus=0; git diff --check=0; negative type-parameter inspect=1 with `UNSUPPORTED_PARAMETER_KIND`; project-root encrypt `--category parameters`=2 with no gate/mapping output.
range_digest: eligible=0a602a2aa4eee4899707481c927b0620025b0f1561e4ff76dfe0dc780096f6f4; preserved=33d7a2f06c13d3c9534fa51c7a7134dba9fbffdca737075f0506a864c4905bc3; all=44f893c8cd48d1031236155113e83b89beaed9cb0dc244e2b7a4717aaafde056.
uncovered_boundaries: T031 does not inventory package/class/interface-own, `$unit`, parameter arrays, string/real/struct parameters, defparam, complex hierarchical references, or macro identifiers without source locations; type parameters fail closed. T031 produces no rewritten RTL, mapping, decrypt, or formal-equivalence artifact; those remain T032 scope.
status_action: changed status to `READY_FOR_REVIEW`; did not set `ACCEPTED`, commit, or push.
```

## 12. 主 Agent 验收结果

主 Agent 已独立重跑并通过全部 T031 门禁：

```text
target_unittest: PASS; 56 tests, OK
full_unittest: PASS; 104 tests, OK
py_compile: PASS; exit 0
positive_inspect_a: PASS; candidate=3, closure=3, definitions=4, modules=2, interfaces=1, eligible=7/19
positive_inspect_b: PASS; byte-identical to report A
report_sha256: 936d1159e8436a4215b499fc5722f77c8929afdd4cff886132dcad5bf1ae1b51
eligible_digest: 0a602a2aa4eee4899707481c927b0620025b0f1561e4ff76dfe0dc780096f6f4
preserved_classification: DATA_WIDTH/LANES=top_parameter; MACRO_LOCAL=macro_expansion
negative_type_parameter: PASS; exit 1, UNSUPPORTED_PARAMETER_KIND
project_root_encrypt_parameters: PASS; expected CLI rejection exit 2, no gate/mapping artifact
verible: PASS; exit 0
iverilog: PASS; exit 0; constant-select warning only
git_diff_check: PASS
formal_verification: N/A; T031 produces no rewritten RTL
fixed_inputs: PASS; positive/negative fixture hashes and range oracle unchanged
acceptance: ACCEPTED
status_action: Main Agent set T031 to ACCEPTED; no commit or push performed
```
