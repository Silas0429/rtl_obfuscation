# T130：完整 filelist 下的 module-local signals 快速交付路径

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 起始分支：`delivery/fast-local-signals`
- 起始提交：`43c6e7c`

## 1. 单一目标

在不改变用户 CLI、MappingVNext schema、物理 byte-range 改写、原子发布和 byte-identical restore 的前提下，为以下精确输入增加快速路径：

```sh
python rtl_encrypt.py \
  --filelist "$FILELIST" \
  --rewrite-root "$REWRITE" \
  --category signals \
  --output-dir "$OUT"
```

完整 filelist 只负责编译顺序、预处理和外部依赖上下文；改名候选只来自 rewrite-root 内显式 source unit 的 module-owned `VariableSymbol/NetSymbol`，每条可改名记录的 declaration 和全部 occurrence 必须位于同一个 physical file 和同一个 semantic module owner。不得建立全工程 SourceCatalog inventory、top closure、semantic owner registry 或通用 RenameIndex workset。

该路径必须保持 fail-closed：不能证明 module-local、同文件、非 port 和唯一 semantic binding 的对象只能保留或拒绝，不能猜测和不能回退到慢速全工程分析。

## 2. 固定输入

主 Agent 冻结只读 fixture：

```text
tests/fixtures/t130_fast_local_signals/design.f
tests/fixtures/t130_fast_local_signals/formal.f
tests/fixtures/t130_fast_local_signals/external/context.sv
tests/fixtures/t130_fast_local_signals/owned/leaf_a.sv
tests/fixtures/t130_fast_local_signals/owned/leaf_b.sv
tests/fixtures/t130_fast_local_signals/owned/top.sv
```

公开正例固定为：

```text
filelist     = tests/fixtures/t130_fast_local_signals/design.f
rewrite-root = tests/fixtures/t130_fast_local_signals/owned
top          = omitted
category     = signals exactly once
name-length  = 20
rate         = disabled
```

fixture 的 `external/context.sv` 同时包含 package global、struct 类型/字段、interface 成员和 vendor module 内部同名 `state`；它们必须逐字节只读。`owned/leaf_a.sv` 与 `owned/leaf_b.sv` 各有独立的 module signal `state`；`leaf_b` 另有同名 function-local `state`，不得与 module signal 合并或改写。ports、function-local 变量、package/interface/struct 对象均不得形成 fast signals mapping。

## 3. 冻结实现边界

### 3.1 快速路径分派

只有以下条件全部成立时允许进入快速路径：

```text
SourceSet.origin == "filelist"
SourceSet.rewrite_roots 非空
normalized categories == ("signals",)
SourceSet.top is None
encryption_rate is None
```

任一条件不满足时继续走当前通用 vNext 流程，行为与 schema 不变。快速路径内部失败必须原子失败，不得捕获后回退到通用慢路径。

### 3.2 允许复用的骨架

- 继续使用现有 SourceSet/filelist 顺序、include、define、`-v`、`.h/.vic` 和物理输入清单；
- 继续使用 PySlang 11 的一次完整 filelist parse/preprocess 与 Compilation 上下文；
- 继续使用当前 `SourceSymbol`、`RenameDecision`、`RenameIndex`、MappingVNext、name factory、range audit、gate byte edit、manifest、restore、metrics 与原子输出；
- 允许为 fast catalog 增加不进入 portable report 的私有 mode/unavailable-name 数据，但不得伪造外部文件可改写记录或改变 schema 版本；
- 输出 gate 的严格检查只需要复用同一 compile context 重新执行 parse/Compilation/diagnostics，不得为了读取诊断再次构建完整 SourceCatalog。

### 3.3 唯一允许改名的对象

一条 `signals` 记录只有同时满足以下条件才可 `rename`：

1. PySlang 直接对象是 `VariableSymbol` 或 `NetSymbol`；
2. `declaringDefinition.definitionKind == Module`；
3. declaration 是该 module body 的直接 signal 成员，不是 task/function/block/generate 内局部声明；
4. 不是任一 `PortSymbol.internalSymbol`；
5. declaration 位于 rewrite-root 内的显式 `.sv/.v` source unit；
6. declaration 与全部 occurrence 位于同一个 physical file；
7. 每个 occurrence 由 PySlang 直接 target identity 绑定到该 declaration，且遍历不得进入子 module/interface instance body；
8. 所有 physical ranges 都逐字节匹配原名、互不重复且互不重叠；
9. 在所属 module CST 范围内，原名的每个 identifier token 都能归属为该 signal 的 declaration/occurrence，或另一个有唯一 physical declaration 的同名对象；存在未归属 token 时该 signal 以既有 `incomplete_name_coverage` 保留；
10. 新名字不与目标 module 语义名字或本批次已生成名字冲突。

同名 module signals 以 `(file, module declaration, signal declaration)` 区分，必须产生两个不同 symbol id 和两个不同新名字。struct/union 字段、interface 成员、package/global、parameter、genvar、module port、subroutine/local variable 和 module/instance/type 名称不产生 fast mapping edit。

### 3.4 性能结构要求

- source fast path 不得调用 `build_source_catalog()` 或 `build_rename_index()`；
- gate strict validation 不得调用 `build_source_catalog()`；
- 不得调用 `catalog_root.visit(...)` / `root.visit(...)` 收集全工程 semantic inventory；
- 只允许遍历 rewrite-root 目标 module 的 semantic body/CST，并在遇到子 instance body 时停止；
- 不得按 rewrite-root 文件数量重新 parse 完整 filelist；完整 filelist source parse 只允许一次，gate validation 另一次；
- 运行 stderr 不得出现 `compile.catalog_inventory`、`compile.top_closure`、`compile.owner_registry` 或通用 `rename_index.semantic_inventory` 子阶段；
- 测试必须通过 mock/visit guard 证明两处 `build_source_catalog` 和通用 `build_rename_index` 均未被调用，不能只比较小 fixture 的墙钟时间。

## 4. 预期机器可读结果

公开 CLI 保持：

```text
format         = rtl-obfuscation.cli-vnext
schema_version = 2
exit           = 0
```

固定正例必须满足：

```text
summary.strict_compile_passed      = true
summary.restored_byte_identical    = true
summary.unsupported                = 0
modified files                     = owned/*.sv only
external/context.sv                = byte-identical
mapping categories                 = signals only
```

mapping 中 module-owned 原名至少精确包含：

```text
t130_leaf_a: state, next_state
t130_leaf_b: state
t130_top: left_value, right_value, combined
```

两个 `state` 必须有不同 `symbol_id`、不同 `semantic_owner` 和不同 `renamed_name`。以下名字不得产生 rename edit：

```text
clk_i data_i data_o left_i right_i value
global_state packet_t payload ready
t130_context_pkg t130_context_if t130_vendor_cell
```

## 5. 不包含

- 不实现 ports/interface/struct 或 `all` 的快速路径；
- 不实现 project-root、single-file、带 `--top` 或带 `--encryption-rate` 的快速路径；
- 不修改 filelist parser、SourceSet schema、MappingVNext schema、restore schema 或公开 CLI 参数；
- 不对 rewrite-root 外文件建立改名候选；`-v` 仍不表示只读；
- 不用字符串全局替换、正则绑定、名称猜测、异常吞掉或静默 fallback；
- 不承诺字符串形式的 UVM/DPI/PLI 层次路径；静态跨 module 引用若未同步必须由 gate compile 失败并原子拒绝；
- 不运行真实 AIClusterWrapper，不加入磁盘缓存、并行、compiled library 或 analysis-root；
- 不删除、放宽或重写历史测试和 fixture。

## 6. 允许修改文件

子 Agent 只能修改：

```text
docs/tasks/T130_fast_local_signals_delivery.md
rtl_obfuscator/fast_local_signals.py
rtl_obfuscator/orchestration_vnext.py
rtl_obfuscator/source_catalog.py
rtl_obfuscator/mapping_vnext.py
rtl_obfuscator/rewrite_vnext.py
rtl_obfuscator/performance_probe.py
tests/test_t130_fast_local_signals.py
README.md
docs/systemverilog_renaming_table.md
```

第 2 节 fixture 是主 Agent 已冻结的只读输入，子 Agent 不得修改。需要修改 `project_discovery.py`、`source_set.py`、现有测试、fixture、schema 或其他文件时，先记录偏差并停止，不得扩大范围。

## 7. 固定验收命令

本任务属于 rewrite/mapping 快速 adapter，固定五条：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t130_fast_local_signals -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t125_single_view_rewrite_root_catalog \
  tests.test_t129_ordered_semantic_workset -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/fast_local_signals.py \
  rtl_obfuscator/orchestration_vnext.py \
  rtl_obfuscator/source_catalog.py \
  rtl_obfuscator/mapping_vnext.py \
  rtl_obfuscator/rewrite_vnext.py \
  rtl_obfuscator/performance_probe.py \
  tests/test_t130_fast_local_signals.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T130_fast_local_signals_delivery.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t130_ready_for_review=pass")'
```

目标 unittest 必须内部完成：公开 CLI 正例、外部文件 byte-identical、范围/module/file 边界、同名 module signal 分离、port/local/package/interface/struct 排除、慢路径 mock guard、actual gate strict compile、decrypt byte identity，以及以下 compact Formal 正负例。

Formal 正例：

```text
gold-filelist = tests/fixtures/t130_fast_local_signals/formal.f
gold-root     = tests/fixtures/t130_fast_local_signals
gate-filelist = <actual gate>/formal.f
gate-root     = <actual gate>
top           = t130_top
command       = conda run -n rtl_obfuscation python scripts/formal_equivalence.py ...
required      = exit 0 and JSON formal_equivalence=pass
```

固定功能负例从同一 actual gate 仅把 `owned/top.sv` 中唯一 `1'b0` 改成 `1'b1`，要求 Formal 非零，并包含 `unproven` 与 `equiv_status -assert`。

子 Agent 编辑实现文件前只运行以下 baseline，预期输出 `baseline_current_slow_path=pass`，证明同一公开输入当前仍调用通用 SourceCatalog：

```sh
conda run -n rtl_obfuscation python -c 'from pathlib import Path; from tempfile import TemporaryDirectory; from unittest.mock import patch; from rtl_obfuscator.orchestration_vnext import OrchestrationVNextError, run_vnext; from rtl_obfuscator.source_set import from_filelist; root=Path("tests/fixtures/t130_fast_local_signals"); source=from_filelist(filelist=root/"design.f", rewrite_roots=(root/"owned",)); tmp=TemporaryDirectory(); base=Path(tmp.name); p=patch("rtl_obfuscator.orchestration_vnext.build_source_catalog", side_effect=RuntimeError("t130 slow path")); p.start(); caught=False
try:
 run_vnext(source, categories=("signals",), gate_dir=base/"gate", restore_dir=base/"restore")
except OrchestrationVNextError as error:
 caught="t130 slow path" in error.message
finally:
 p.stop(); tmp.cleanup()
assert caught; print("baseline_current_slow_path=pass")'
```

## 8. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 43c6e7c7575110d7c12457a37dacdcdf9caab808
changed_files: "docs/tasks/T130_fast_local_signals_delivery.md; rtl_obfuscator/fast_local_signals.py; rtl_obfuscator/orchestration_vnext.py; rtl_obfuscator/source_catalog.py; rtl_obfuscator/mapping_vnext.py; rtl_obfuscator/rewrite_vnext.py; tests/test_t130_fast_local_signals.py; README.md"
commands: "start 2026-09-02 14:52:50 +0800; baseline; PySlang API probes for named conditional generate, for-generate/GenerateBlockArraySymbol, and InstanceArraySymbol direct members; conda run -n rtl_obfuscation python -m unittest tests.test_t130_fast_local_signals -v; conda run -n rtl_obfuscation python -m unittest tests.test_t125_single_view_rewrite_root_catalog tests.test_t129_ordered_semantic_workset -v; conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/fast_local_signals.py rtl_obfuscator/orchestration_vnext.py rtl_obfuscator/source_catalog.py rtl_obfuscator/mapping_vnext.py rtl_obfuscator/rewrite_vnext.py rtl_obfuscator/performance_probe.py tests/test_t130_fast_local_signals.py; git diff --check HEAD; public rtl_decrypt.py byte-identity check; actual-gate formal positive/negative commands after fixture correction; READY_FOR_REVIEW status guard; CHANGES_REQUESTED corrections: direct scope-member hierarchy discovery, helper guard, generate array/for regression"
results: "baseline_current_slow_path=pass; T130 unittest 9/9 including named conditional generate, for-generate, instance-array, direct-scope helper guard, stage envelope, decrypt byte identity, actual-gate Formal positive/negative; T125/T129 12/12; py_compile pass; diff-check pass; CLI schema 2 and summary strict_compile_passed/restored_byte_identical true, mapping 6 signals, external context unchanged; public decrypt exit 0 and restored_byte_identical true; fast stage guard has compile/rename_index/mapping/gate/restore begin/end and no compile.catalog_inventory/compile.top_closure/compile.owner_registry/rename_index.semantic_inventory; hierarchy discovery uses no body.visit; Formal positive exit 0 JSON formal_equivalence=pass; fixed 1'b0-to-1'b1 negative exit 1 with unproven and equiv_status -assert; t130_ready_for_review=pass"
schema_or_behavior: "Fast dispatch requires filelist + rewrite_roots + categories=(signals,) + top=None + encryption_rate=None; target modules are resolved by direct semantic scope-member enumeration, recursing only GenerateBlockSymbol/GenerateBlockArraySymbol/InstanceArraySymbol and collecting isModule InstanceSymbol edges; hierarchy discovery never opens InstanceBodySymbol.visit, while _semantic_ranges retains target body.visit with child InstanceBodySymbol VisitAction.Skip; only module-direct VariableSymbol/NetSymbol are candidates; Mapping/Rewrite/Restore schema remains v2; compile/rename_index/mapping/gate/restore outer envelope is preserved; gate strict validation uses one diagnostics-only compile callback"
boundaries: "none; frozen fixture remained read-only (the main Agent corrected the Yosys-incompatible function assignment before final Formal rerun); generated-module and direct-scope regressions use only TemporaryDirectory source text"
cleanup_candidates:
formal_verification: "PASS; gold tests/fixtures/t130_fast_local_signals/formal.f, gate actual output/formal.f, top t130_top, seq 5; positive exit 0 with JSON formal_equivalence=pass; fixed functional negative exit 1 with unproven and equiv_status -assert"
review_request: "requested; all five contract acceptance rows and exact READY_FOR_REVIEW guard pass; no commit/push"
```

## 9. 偏差或阻塞

```text
none (resolved): the initial Formal parse issue was corrected by the main Agent; direct scope-member hierarchy discovery now covers named conditional generate, for-generate and instance-array edges without opening module bodies. The helper guard, stage-envelope and README findings are fixed and covered by the target tests. No fixture or out-of-allowlist file was changed by this sub-agent.
```

## 10. 主 Agent 验收记录

```text
status: ACCEPTED
reviewed_head: 43c6e7c7575110d7c12457a37dacdcdf9caab808 plus the uncommitted T130 delivery diff
acceptance: "PASS; main Agent independently ran all five frozen rows: T130 9/9, T125/T129 12/12, py_compile exit 0, git diff --check HEAD exit 0, READY_FOR_REVIEW guard exit 0"
code_review: "PASS; exact fast dispatch only, no slow fallback, direct hierarchy scope-member edges only, target semantic body/CST only for signal ranges, gate diagnostics-only compilation, schema/atomic rewrite/restore unchanged"
blocking_findings: none
resolution: "generate-only, for-generate and instance-array target modules resolve without catalog_root.visit/root.visit or hierarchy-discovery body.visit; compile/rename_index/mapping/gate/restore stage envelope and README boundary are present"
formal_verification: "PASS; main Agent reran tests.test_t130_fast_local_signals, whose public actual-gate Formal positive exited 0 with formal_equivalence=pass and whose fixed 1'b0-to-1'b1 negative exited nonzero with unproven and equiv_status -assert"
next_step: "publish this accepted branch and validate the same unchanged CLI on AICluster; no additional implementation task is opened here"
```
