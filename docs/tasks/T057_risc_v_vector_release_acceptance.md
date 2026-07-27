# T057：RISC-V-Vector vNext 专项发布验收

- 状态：READY
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R5-B（最终阶段）
- 前置任务：T056 `ACCEPTED`
- 设计基线：`97f2cd0e7b4f92a5f5a308d7de5bc8670fb8e8d8`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 6–8 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- Formal 依据：`docs/formal_verification.md`
- 验收类型：RISC 发布验收；本任务明确授权且必须运行一次 RISC-V-Vector 正例和功能负例 Formal

## 1. 单一目标

用当前唯一 vNext 产品流水线完成 `RISC-V-Vector/vector_top` 的真实 project-root
加密、strict gate、跨进程恢复和 Yosys 等价证明；同时将 residual T029 legacy acceptance
stack 替换为：

1. 不含 RISC 路径或固定场景数量的通用 vNext Formal-view/alignment 引擎；
2. 只在本专项任务运行、持有 RISC 场景 oracle 的发布验收脚本；
3. 不再依赖 `inventory.py`、`category_profile.py`、legacy `project.py`、旧 mapping
   v1–v4 或已删除产品 CLI 的测试。

T057 `ACCEPTED` 即表示 R0–R5 本轮重构交付完成，不创建 T058。

## 2. 主 Agent 起始审计

### 2.1 干净基线

```text
contract_baseline_head: 97f2cd0e7b4f92a5f5a308d7de5bc8670fb8e8d8
contract_baseline_branch: main...origin/main
contract_baseline_worktree: clean
baseline_command:
  conda run -n rtl_obfuscation python -m unittest
  tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals
  tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters
  tests.test_vnext_product_surface -v
baseline_result: exit_code=0; Ran 71 tests in 2.206s; OK
```

### 2.2 residual stack

当前 residual 仍包含：

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/category_profile.py
rtl_obfuscator/project.py
rtl_obfuscator/formal_view.py
scripts/t029_acceptance.py
tests/test_risc_v_vector_project_root.py
```

其中旧 `formal_view.py` 导入 legacy inventory/project，`align_formal_view()` 在通用实现内硬编码
`1091 / 5741 / 5527`；旧脚本和测试调用已经从产品 parser 删除的
`inspect-project / encrypt-project / decrypt-project / formal-view / formal-align`。
不得直接重跑或恢复这些旧 CLI。

### 2.3 已复现的 vNext 首批阻塞

主 Agent 未运行 RISC Formal，只对固定输入执行了分层只读诊断。当前
`encrypt-vnext --project-root ... --top vector_top` 首先失败于：

```text
SOURCESET_DISCOVERY_FAILED:
include dependency is not a .svh header: rtl/vector/vmacros.sv
```

绕过该单点限制后的语义诊断又确认以下边界：

```text
CATALOG_RANGE_INVALID:
rtl/vector/vis.sv:20065 anonymous generate owner has no source name token

SYMBOL_GRAPH_UNSUPPORTED_REFERENCE:
rtl/shared/eb_buff_generic.sv:1577 contains an UninstantiatedDefSymbol

SYMBOL_GRAPH_UNSUPPORTED_SOURCE:
NamedValueExpression VECTOR_LANE_NUM has no direct syntax identifier,
but its semantic sourceRange bytes are exactly VECTOR_LANE_NUM

SYMBOL_GRAPH_RANGE_CONFLICT:
declaration was repeated as an occurrence; genvar k was also collected as signals
```

这些是本任务唯一预授权的产品核心修正类别。不得把后续任意失败概括为“RISC 兼容”后扩大范围。

## 3. 固定输入与选择

```text
project_root: rtl_samples/RISC-V-Vector
top: vector_top
defines: none
include_dirs: none
encryption_rate: none
name_length: 20
categories: CANONICAL_CATEGORIES（19 类全部）
abi_categories: MODULE_ABI_CATEGORIES（11 类全部）
input_manifest_sha256: a016dd548525346508c636b97fcc452c8f6eb4fcbf930ef5eb938a2edfa2ae9d
reachable_modules: 17
physical/closure files: 19
```

compile order 必须保持：

```text
rtl/shared/and_or_mux.sv
rtl/shared/eb_one_slot.sv
rtl/shared/eb_buff_generic.sv
rtl/shared/fifo_duth.sv
rtl/vector/v_fp_alu.sv
rtl/vector/vmacros.sv
rtl/vector/v_int_alu.sv
rtl/vector/vex_pipe.sv
rtl/vector/vrat.sv
rtl/vector/vrf.sv
rtl/vector/vstructs.sv
rtl/vector/vex.sv
rtl/vector/vis.sv
rtl/vector/vmu_ld_eng.sv
rtl/vector/vmu_st_eng.sv
rtl/vector/vmu_tp_eng.sv
rtl/vector/vmu.sv
rtl/vector/vrrm.sv
rtl/vector/vector_top.sv
```

不得修改 `rtl_samples/RISC-V-Vector/**` 来满足这些 oracle。

## 4. 允许的产品核心修正

### 4.1 `.sv` include provider

- project-root discovery 允许候选闭包内 `.sv` 作为 include provider；
- `.sv` provider 仍按 SystemVerilog source unit 出现在唯一 compile order，不复制内容、不改后缀；
- `.svh` 继续作为 included physical file；
- physical manifest 必须去重，filelist 顺序规则和现有 `.svh` 行为不变；
- 不允许按 RISC 路径、文件名或 module 名分支。

### 4.2 owner 与匿名 generate

- explicit generate label 继续产生 `generate_blocks` record；
- PySlang 自动生成的 `genblkN` 没有 source token，不得伪造 declaration 或 rename record；
- anonymous generate 只用 syntax source span 注册稳定 owner，使其内部 byte-backed symbol
  可以归属；
- owner registry 仍要求 physical range、唯一性和 fail-closed。

### 4.3 elaboration 与 source identity

- `UninstantiatedDefSymbol` 本身不是 source identifier，不得导致整个 selected-top graph 失败；
- graph 必须从 catalog/top overlay 中保留实际 elaborated、byte-backed source symbols；
- 同一 category、name、owner、declaration 和 occurrence range 的重复 elaboration幂等合并；
- 不同 category、不同 owner 或不同 symbol 的 exact/partial overlap 继续
  `SYMBOL_GRAPH_RANGE_CONFLICT`；
- 不允许以运行时 object identity、fixture 名称或固定数量去重。

### 4.4 semantic range fallback

引用范围优先使用直接 syntax identifier。只有同时满足以下条件才允许 fallback：

1. PySlang semantic target 已绑定；
2. semantic `sourceRange` 起止位于同一 SourceSet physical file；
3. 非 macro location；
4. `source[start:end] == bound_name.encode("utf-8")`；
5. range 未与其他 source symbol 冲突。

不得在文件或 syntax subtree 中全文搜索名称。条件不满足时保持稳定 fail-closed。

### 4.5 declaration、genvar 与 signal

- declaration range 不得再次作为 occurrence；
- genvar declaration/reference 只属于 `genvars`，不得同时进入 `signals`；
- 排除必须基于 semantic kind/declaration identity，不得仅按名称排除；
- T042 parameter/genvar、现有 repeated-instance 和 range 冲突回归必须继续通过。

除第 4.1–4.5 节外，若 RISC gate 还需要修改 product mapping、rewrite、rate、metrics、restore、
CLI schema 或 category policy，子 Agent 必须记录首个对象、文件、range 和错误码并设为
`BLOCKED`，不得自行继续。

## 5. 通用 Formal vNext 引擎

删除 legacy `rtl_obfuscator/formal_view.py`，新增
`rtl_obfuscator/formal_vnext.py`。该模块只提供程序化 API，不接入产品 argparse：

```text
build_formal_view_vnext(
    source_set: SourceSet,
    *,
    output_dir: Path,
    manifest_path: Path,
) -> dict

align_formal_view_vnext(
    *,
    gate_dir: Path,
    gate_view_dir: Path,
    gate_view_manifest_path: Path,
    orchestration_report_path: Path,
    output_dir: Path,
    manifest_path: Path,
) -> dict
```

允许参数名做不改变数据流的轻微调整，但以下语义冻结：

- `build_formal_view_vnext` 只消费既有 `SourceSet` / `SourceCatalog` semantic view；
- 保留现有三种 Yosys compatibility transformation：
  `lower_packed_aggregate_type`、`lower_packed_struct_member`、
  `remove_concurrent_assertion`；
- transformation 必须有 physical range、source/replacement hash、structural ordinal；
- gold/gate view 的 normalized transformation signature 必须对称；
- alignment 只消费 actual gate、gate formal view 和持久化
  `rtl-obfuscation.orchestration-vnext` report，不读取 gold；
- report 必须校验 format/schema/state、SourceSet、input/gate manifest、effective mapping、
  renamed name 唯一性和 gate-view hash chain；
- alignment 只反向替换 effective mapping 中 `action=rename` 的 identifier；
- identifier replacement 数量从输入计算，通用模块中不得出现 RISC 路径、top、文件数、
  mapping count、occurrence count、replacement count 或 manifest 常量；
- build/align 重复运行结果 byte-identical；
- 输出目录和 manifest 原子发布；tamper、路径冲突、lexer/Yosys 失败不留部分输出；
- 不增加 `formal-view` / `formal-align` 产品 CLI，也不建立第二套 inventory/SymbolGraph。

## 6. RISC 场景驱动与 release oracle

删除 `scripts/t029_acceptance.py`，新增：

```text
scripts/risc_v_vector_acceptance.py
```

唯一用户参数：

```text
--work-dir <absent-or-empty-directory>
```

驱动必须：

1. 通过子进程调用 actual `encrypt-vnext`，使用第 3 节完整 category/ABI 选择；
2. 验证 19-file SourceSet、17 modules、固定 input manifest、strict compile、
   mapping/range/metrics hash chain；
3. 通过独立 `decrypt-vnext` 进程恢复，19 个 physical files byte-identical；
4. 对 original source root 和 actual gate 分别调用通用 Formal-view API；
5. 仅用 gate report 和 gate view 调用 alignment；
6. 对 gold/gate transformation signature、Yosys warnings 和重复运行 determinism 做归一比较；
7. 运行 `scripts/formal_equivalence.py`：

```text
gold: <work-dir>/formal-gold
gate: <work-dir>/formal-aligned
top: vector_top
seq: 1
```

8. 正例退出 0，JSON `formal_equivalence=pass`；
9. 从 actual aligned gate 复制负例，仅把
   `rtl/vector/vector_top.sv` 中 `assign vector_idle_o = ...` 表达式内一个 ASCII `&`
   改为 `|`；修改前后长度相同且恰好一个 byte 不同；
10. 负例先通过相同 Yosys strict view check，再运行相同 Formal；必须非零并包含
    `unproven` 和 `equiv_status -assert`；
11. 输出单行 canonical JSON：

```json
{
  "format": "rtl-obfuscation.risc-v-vector-vnext-acceptance",
  "schema_version": 1,
  "status": "pass",
  "input": {},
  "mapping": {},
  "metrics": {},
  "restore": {},
  "formal_view": {},
  "formal_alignment": {},
  "formal_positive": {},
  "formal_negative": {}
}
```

场景脚本可以持有且必须最终冻结以下 literal oracle；通用模块不得持有：

- normalized SourceSet digest；
- normalized MappingVNext range digest；
- mapping total/rename/preserve/unsupported counts；
- modified-token count；
- 19 类 per-category action counts；
- Formal-view transformation 总数、kind counts 和 signature digest；
- alignment identifier replacement count 和 aligned view manifest；
- 正例 top/seq/status与负例 changed file/byte/unproven 摘要。

这些值不得沿用旧 `1091 / 5741 / 5527`。确定新 oracle 的流程固定为：

1. actual product path 连续运行两次；
2. random `renamed_name`、随机 gate hash、临时绝对路径不进入 normalized digest；
3. 两次 normalized 值必须完全一致；
4. 将一致值写成场景 literal；
5. 删除临时输出后第三次运行，必须由 literal 比较通过；
6. 执行记录写出 literal 和 canonical digest 算法；主 Agent独立重算后才能接受。

mapping range digest 输入固定为按 `symbol_id` 排序的以下字段：

```text
symbol_id, category, action, reason, original_name,
owner_module, semantic_owner, declaration,
occurrences(source_range + provenance), impact, abi
```

明确排除 `renamed_name` 和绝对路径。不得用 exact random name 控制产品行为。

## 7. residual 删除与测试迁移

任务完成时删除：

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/category_profile.py
rtl_obfuscator/project.py
rtl_obfuscator/formal_view.py
scripts/t029_acceptance.py
```

现有测试中仅为 mock legacy builder 而导入这些模块的部分必须改为产品 import-surface /
唯一 discovery identity 断言；不得保留空壳 module、re-export、fallback 或 converter。

`tests/test_risc_v_vector_project_root.py` 改写为 vNext 测试，至少覆盖：

- 第 4 节全部已知边界；
- generic Formal build/align compact transaction/tamper 测试；
- release driver 的 JSON schema/oracle helper；
- 不在该 unittest 内重复完整 RISC Yosys 正负证明，完整证明只由第 10 节专项脚本运行一次。

历史任务文档可保留旧事实；当前 README、Formal、future-work 和 R5 plan 必须只描述 vNext
产品与 T057 专项发布流程。

## 8. 允许修改的文件

实现：

```text
rtl_obfuscator/project_discovery.py
rtl_obfuscator/source_set.py
rtl_obfuscator/source_catalog.py
rtl_obfuscator/symbol_graph.py
rtl_obfuscator/formal_vnext.py                 # 新增
rtl_obfuscator/inventory.py                    # 删除
rtl_obfuscator/category_profile.py             # 删除
rtl_obfuscator/project.py                      # 删除
rtl_obfuscator/formal_view.py                  # 删除
scripts/risc_v_vector_acceptance.py            # 新增
scripts/t029_acceptance.py                     # 删除
```

测试：

```text
tests/test_source_set.py
tests/test_source_catalog.py
tests/test_symbol_graph_signals.py
tests/test_symbol_graph_genvars.py
tests/test_symbol_graph_parameters.py
tests/test_rewrite_policy.py
tests/test_mapping_vnext.py
tests/test_rewrite_vnext.py
tests/test_vnext_product_surface.py
tests/test_risc_v_vector_project_root.py
```

文档：

```text
README.md
docs/formal_verification.md
docs/future_work.md
docs/three_mode_refactor_plan.md
docs/tasks/T057_risc_v_vector_release_acceptance.md
```

不允许修改：

```text
rtl_samples/RISC-V-Vector/**
tests/fixtures/**
scripts/formal_equivalence.py
rtl_obfuscator/rewrite.py
rtl_obfuscator/rewrite_vnext.py
rtl_obfuscator/orchestration_vnext.py
rtl_obfuscator/restore_vnext.py
rtl_obfuscator/mapping_vnext.py
rtl_obfuscator/rewrite_policy.py
rtl_obfuscator/metrics_vnext.py
rtl_obfuscator/rate*.py
encrypt.py
历史任务合同
```

需要修改允许列表外文件时，记录首个具体原因并停止。

## 9. 明确不包含

- 不新增 category、mapping schema、CLI operation、rate 模式或兼容层；
- 不修改 RISC RTL、SVA、simulator、generated decoder result；
- 不恢复 legacy inspect/encrypt/decrypt/formal CLI；
- 不按 RISC path、module、fixture 或旧 count 在产品代码分支；
- 不使用 lexical 全文搜索、identity Formal、复制 gold、忽略 diagnostic 或移除
  `equiv_status -assert`；
- 不运行 blanket unittest discovery；
- 不做性能优化、缓存、新依赖或 T058。

## 10. 验收命令

子 Agent先运行第 2.1 节 baseline。最终只运行以下五条：

```sh
conda run -n rtl_obfuscation python scripts/risc_v_vector_acceptance.py --work-dir /private/tmp/rtl-obfuscation-t057-release

conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_symbol_graph_signals tests.test_symbol_graph_genvars tests.test_symbol_graph_parameters tests.test_rewrite_policy tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_mapping_execution_vnext tests.test_metrics_vnext tests.test_rate_vnext tests.test_rate_execution_vnext tests.test_rate_metrics_vnext tests.test_orchestration_vnext tests.test_cli_vnext_encryption tests.test_restore_vnext tests.test_project_root_vnext tests.test_project_root_inspect tests.test_formal_equivalence tests.test_encrypt_demo tests.test_vnext_category_closure tests.test_vnext_product_surface tests.test_risc_v_vector_project_root -v

conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/*.py encrypt.py scripts/formal_equivalence.py scripts/risc_v_vector_acceptance.py tests/test_*.py

git diff --check HEAD

rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T057_risc_v_vector_release_acceptance.md
```

第一条允许最多 1200 秒；必须从不存在的 work-dir 开始。若目录已存在，先选择新的明确路径，
不得删除用户目录。第一条已包含本任务唯一一次 RISC 正负 Formal，第二条不得再次运行完整
RISC Formal。

由于 `git diff --check HEAD` 不覆盖 untracked 新文件，子 Agent必须在执行记录单列新增文件；
主 Agent review 时会在不改变内容的前提下暂存全部 T057 文件并额外执行
`git diff --cached --check`，任何新文件 whitespace 错误均退回。

## 11. Formal verification 交付格式

```text
formal_verification: PASS | FAIL | BLOCKED
gold: <absolute work-dir>/formal-gold/design.f
gate: <absolute work-dir>/formal-aligned/design.f
top: vector_top
seq: 1
positive_command: <exact command>
positive_exit_code: 0
positive_result: <JSON containing formal_equivalence=pass>
negative_file: rtl/vector/vector_top.sv
negative_change: one ASCII byte & -> |
negative_strict_view: PASS
negative_command: <exact command>
negative_exit_code: nonzero
negative_result: contains unproven and equiv_status -assert
```

缺少任一项、超时、unsupported、正例失败或负例意外通过，均不得设置
`READY_FOR_REVIEW`。

## 12. 停止条件

出现以下任一情况立即记录并设为 `BLOCKED`：

- fixed RISC input manifest 或 19-file compile order 与第 3 节不一致；
- 必须修改 RISC fixture、Formal 脚本或产品 schema；
- semantic fallback 不能满足第 4.4 节精确 byte 规则；
- 不同 source identity 仍竞争同一 physical range；
- strict gate 只能通过保留所有对象、删除真实 reference 或忽略 diagnostic；
- alignment 必须读取 gold 或使用旧 mapping；
- Formal 只能通过 identity、复制 gold、降低证明强度或硬编码通用引擎数量；
- 新 oracle 两次 normalized run 不一致。

## 13. 子 Agent 执行记录

开始前填写并把状态改为 `IN_PROGRESS`：

```text
status:
starting_head:
starting_worktree:
baseline_command:
baseline_result:
allowed_files_confirmed:
```

申请 review 前填写：

```text
changed_files:
deleted_files:
commands:
results:
known_boundary_fixes:
source_set_digest:
mapping_range_digest:
mapping_counts:
per_category_counts:
formal_view_oracle:
formal_alignment_oracle:
restore_identity:
legacy_residual_check:
formal_verification:
boundaries:
review_request:
```

子 Agent不得执行 `git add`、`commit`、`push`，不得设置 `ACCEPTED`，不得创建 T058。

## 14. 主 Agent 验收记录

待 `READY_FOR_REVIEW` 后填写。主 Agent只依据第 10–12 节冻结矩阵复验，不追加新的 count、
fixture 或隐藏 probe。
