# T126：SourceCatalog source-backed owner 边界

- 状态：`ACCEPTED`
- 设计负责人：主 Agent Codex
- 实现负责人：子 Agent（`gpt-5.6-luna`，`xhigh`）
- 前置任务：T125 已由主 Agent验收，交付提交 `84209846078fe4fc48f314c723125a3a066dce51`
- 任务类型：SourceCatalog / source-range correction
- Formal verification：`N/A`；本任务不修改 rewrite/mapping 行为，也不以任务验收产生 rewritten RTL

## 1. 已冻结的根因

PySlang 11.0.0 会为 class、covergroup 等语义对象建立无物理源码的合成
`SubroutineSymbol`。服务器证据固定为：

```text
BufferKind.Unknown
full_path='.'
offset=68719476735
source_text_length=0
```

当前 `_semantic_owner_ids()` 对所有 `SubroutineSymbol` 建立物理 owner；`_relative_file()` 又在
`SourceSet.source_root == /` 时把 `.` 解析为当前工作目录，最终将目录和哨兵 offset 送入物理 token
读取。逻辑缺陷由 T056 `97f2cd0` 引入；T108 `d1c45b6` 将产品缩减为四核心组时保留了已经无消费者的
subroutine/generate 全量 owner 扫描；T125 `8420984` 让真实 filelist 到达该阶段并把错误稳定显式化。

这不是 PySlang 编译错误，也不是 rename/rewrite 错误。T126 不按 `randomize`、`pre_randomize`、供应商
文件名或具体语法建立白名单。

## 2. 单一目标

让 SourceCatalog 只注册当前四核心组实际可消费、且能证明唯一物理声明的 semantic owner；在一个统一
入口拒绝把 Unknown/Macro/目录/未列入 SourceSet 的 buffer 当作普通物理文件。PySlang 合成且无源码的
semantic node 不产生 owner，也不阻塞只读依赖参与完整 filelist 编译。

完成后必须同时成立：

1. filelist + explicit top + rewrite root 中，rewrite root 外的 class/covergroup 合成方法不阻塞 catalog；
2. module、interface、真实 typedef owner 仍保持原有稳定物理 ID；
3. 当前 RenameIndex 产生的每个 `semantic_owner` 仍能通过 MappingVNext owner registry 校验；
4. `BufferKind.Unknown` 的 `.` 在 `source_root=/` 时也绝不能解析成 cwd；
5. 用户源码 function/task 仍参与 RenameIndex 的名字完整性声明归属，但不再为已移除的
   function/task category预建 `subroutine:` owner；
6. 不增加具体系统方法名、供应商名、fixture名或异常吞掉式 fallback。

## 3. 成本与影响范围

### 3.1 实现成本

- 中小规模：一个产品模块和一个目标测试模块；预计不需要新增公共抽象、依赖或 schema。
- 统一物理 buffer 判定复用现有 `SourceManager.getBufferKind()`、SourceSet 物理清单和 bounded token read。
- 删除或收窄已经没有四核心组消费者的 subroutine/generate owner 预注册；不重写 RenameIndex。

### 3.2 对外影响

- CLI、`--rewrite-root`、filelist、category、mapping schema、restore schema均不变；
- source-less/implicit/compiler metadata 不产生 edit，与当前重命名表一致；
- rewrite root 外文件继续完整编译并保持只读；
- 当前 PySlang 编译时间和峰值内存不属于本任务，T126 不承诺性能下降；
- 当前服务器错误应消失，但若复测出现与本合同无关的新错误，只记录证据，不扩大 T126。

### 3.3 主要风险

- 过度跳过真实源码 owner，导致 MappingVNext registry 不完整；
- 将 Macro/MacroArg误当普通文件，形成错误物理 edit；
- 为修复 Unknown 而捕获全部 range 异常，掩盖真实源码损坏。

目标测试必须分别锁定真实物理 owner、合成无源码 owner和非物理 buffer fail-closed，禁止宽泛
`except: continue`。

## 4. 固定输入与预期输出

目标测试在临时目录建立固定 compact filelist：

```text
external/context.sv  # class rand member + covergroup + interface，位于 rewrite root 外
owned/top.sv         # t126_top、真实 function/task、typedef struct、可改名 signal
```

SourceSet 固定为：

```text
origin=filelist
top=t126_top
rewrite_roots=(owned,)
categories=all
```

预期机器可检查结果：

- `build_source_catalog()` 成功；
- `semantic_owner_ids` 只含 `$unit`、物理 module/interface/type owner，不含 `subroutine:` / `generate:`；
- class/covergroup 合成方法的 `Unknown` 位置不进入任何物理读取；
- `build_rename_index()` 与 `build_mapping_vnext()` owner 校验成功；
- root `/` + `full_path='.'` 的 fake Unknown buffer稳定拒绝，且错误不把 cwd 报成源文件；
- direct physical buffer 仍按精确 bytes/range 工作，Macro/MacroArg 不被普通物理路径接受。

## 5. 包含与不包含

### 包含

- SourceCatalog 内统一的普通物理 buffer/path 边界；
- `_semantic_owner_ids()` 与当前四核心组消费者对齐；
- class/covergroup合成 subroutine、真实 typedef/interface/module、root `/` 和非物理 buffer 回归；
- 对当前 RenameIndex/Mapping owner 不变量的 compact 验证。

### 不包含

- 不新增或恢复 functions/tasks/arguments/generate_blocks category；
- 不实现 analysis-root、compile-order裁剪、provider overlay、子进程隔离或内存优化；
- 不修改供应商诊断精确放行；
- 不修改 RenameIndex、Mapping、Rewrite、CLI 或公共文档；
- 不按具体 class method、供应商库、文件路径写兼容规则；
- 不处理服务器复测中尚未出现的后续独立问题。

## 6. 允许修改文件

子 Agent 只能修改：

```text
docs/tasks/T126_source_backed_owner_boundary.md
rtl_obfuscator/source_catalog.py
tests/test_t126_source_backed_owner_boundary.py
```

需要修改任何其他文件时，记录偏差并停止，不得扩大范围。

## 7. 实现约束

1. 普通物理声明只接受 PySlang `DesignFile`、`LibraryFile`、`IncludeFile`，并必须解析为 SourceSet 已知的
   普通物理文件；`LibraryMap`、`Unknown`、`Macro`、`MacroArg` 不得经 `Path('.')` fallback。
2. 合成无源码节点的判断必须由 semantic kind + 缺失 syntax/物理 buffer 证据构成，不得按 name判断。
3. 当前四组没有消费者的 `subroutine:` / `generate:` owner 不再全量预注册；RenameIndex 现有声明归属
   逻辑保持不变。
4. 真实 TypeAlias owner 继续注册；source-less TypeAlias wrapper 不得伪造物理 owner。
5. 真正声称 source-backed、但物理范围无效的对象继续稳定 fail-closed；不得捕获后静默成功。
6. 不改变 `SourceCatalog.to_report()`、Mapping schema 或公共输出。

## 8. 固定验收命令

子 Agent 与主 Agent 都只运行以下五条，不追加 blanket discovery 或 RISC Formal：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t126_source_backed_owner_boundary -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_source_catalog \
  tests.test_t125_single_view_rewrite_root_catalog.T125SingleViewRewriteRootCatalogTests.test_single_explicit_top_view_has_cst_inventory_and_one_compile \
  tests.test_t125_single_view_rewrite_root_catalog.T125SingleViewRewriteRootCatalogTests.test_physical_inventory_reads_only_token_sized_ranges \
  tests.test_t125_single_view_rewrite_root_catalog.T125SingleViewRewriteRootCatalogTests.test_readonly_duplicate_matrix_is_finite_and_fail_closed \
  tests.test_mapping_vnext -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/source_catalog.py \
  tests/test_t126_source_backed_owner_boundary.py

git diff --check HEAD

python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T126_source_backed_owner_boundary.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t126_ready_for_review=pass")'
```

验收类型：SourceCatalog/source-range。Formal 为 `N/A`，原因是本任务不改变 rewrite/mapping行为，固定
验收不产生 rewritten RTL。

## 9. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 84209846078fe4fc48f314c723125a3a066dce51
changed_files: docs/tasks/T126_source_backed_owner_boundary.md, rtl_obfuscator/source_catalog.py, tests/test_t126_source_backed_owner_boundary.py
commands: |
  baseline: conda run -n rtl_obfuscation python -m unittest tests.test_t126_source_backed_owner_boundary -v (before implementation; exit 1, target module absent)
  conda run -n rtl_obfuscation python -m unittest tests.test_t126_source_backed_owner_boundary -v (exit 0, 3 tests; includes direct physical package function range and same-name signal completeness)
  conda run -n rtl_obfuscation python -m unittest tests.test_source_catalog tests.test_t125_single_view_rewrite_root_catalog.T125SingleViewRewriteRootCatalogTests.test_single_explicit_top_view_has_cst_inventory_and_one_compile tests.test_t125_single_view_rewrite_root_catalog.T125SingleViewRewriteRootCatalogTests.test_physical_inventory_reads_only_token_sized_ranges tests.test_t125_single_view_rewrite_root_catalog.T125SingleViewRewriteRootCatalogTests.test_readonly_duplicate_matrix_is_finite_and_fail_closed tests.test_mapping_vnext -v (exit 0, 19 tests)
  conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_catalog.py tests/test_t126_source_backed_owner_boundary.py (exit 0)
  git diff --check HEAD (exit 0)
  python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T126_source_backed_owner_boundary.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t126_ready_for_review=pass")' (exit 0)
results: corrected target boundary and compatibility rows pass; regular-file, nonphysical-buffer, synthetic-owner, source-backed declaration-attribution, and mapping-owner checks are covered
schema_or_behavior: _relative_file now accepts only DesignFile/LibraryFile/IncludeFile, only SourceSet-known paths, and only regular files; Unknown/LibraryMap/Macro/MacroArg reject before path resolution. Source-less TypeAliasType wrappers and synthetic SubroutineSymbol/GenerateBlockArraySymbol nodes do not register owners; module/interface/type owner IDs and mapping schema remain unchanged.
boundaries: class/covergroup synthetic methods are tolerated; external interface is readonly outside owned rewrite root; a source-backed package function named shared_name in a different legal scope is directly byte-range validated, and the owned shared_name signal remains eligible rather than incomplete_name_coverage. Known directory/FIFO paths fail closed; no RenameIndex or out-of-scope test change.
cleanup_candidates: none for T126
formal_verification: N/A
reason: no rewritten RTL is produced by this task
review_request: READY_FOR_REVIEW; main agent must independently rerun the same five contract commands and decide acceptance
```

## 10. 主 Agent 验收

```text
main_result: PASS after one bounded rework within the original plan and allowlist
reviewed_head: 84209846078fe4fc48f314c723125a3a066dce51 + T126 working tree
scope_review: PASS; only source_catalog.py, the T126 target test and this task contract changed; no CLI, schema, RenameIndex, Mapping, Rewrite, vendor diagnostic or performance code changed
code_review: PASS; physical buffers are classified before path resolution, must be DesignFile/LibraryFile/IncludeFile, SourceSet-known and regular files; Unknown/LibraryMap/Macro/MacroArg cannot map `.` to cwd; obsolete subroutine/generate owner pre-registration is removed; source-less TypeAlias wrappers do not forge owners; real module/interface/type owners and source-backed function declaration attribution remain intact; no name/vendor/fixture whitelist or broad exception skip was introduced
target_result: PASS; `tests.test_t126_source_backed_owner_boundary`, 3 tests, exit 0
compatibility_result: PASS; exact no-gate SourceCatalog/T125-range/Mapping row, 19 tests, exit 0
py_compile: PASS; exit 0
git_diff_check: PASS; `git diff --check HEAD`, exit 0
ready_for_review_guard: PASS before acceptance; `t126_ready_for_review=pass`
formal_verification: N/A
reason: SourceCatalog/source-range correction; the fixed acceptance produced no rewritten RTL
accepted_by: Main Agent Codex
```

## 11. 验收后的唯一下一步

T126 本地验收、提交并推送后，只使用同一服务器命令复测
`AIClusterWrapper_sim.f + --top AIClusterWrapper + --rewrite-root aic_ss/src`，记录 SourceSet 时间、
catalog/PySlang时间、峰值 RSS、退出状态和首个稳定诊断。不在该复测前创建新的兼容或性能任务；若出现
新问题，只根据证据判断是否属于 T126 回归，不自动扩大实现计划。
