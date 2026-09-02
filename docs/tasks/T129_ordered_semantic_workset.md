# T129：RenameIndex 有序语义工作集与直接索引

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 实现负责人：子 Agent（`gpt-5.6-luna`，`xhigh`）
- 起始 HEAD：`22cbb971b502ef4217777ed991e380d12ecc891e`
- 起始工作树：clean
- 前置任务：T128 已由主 Agent 验收并以 `22cbb97` 推送
- 任务类型：RenameIndex 内部结构性性能优化；公共行为和逐项决策必须完全一致
- Formal verification：`REQUIRED`；本任务改变 RenameIndex 建立声明与 occurrence 证据的执行结构，必须以实际 compact gate 正例和固定功能负例验证

## 1. 已冻结的问题与并行服务器基线

AIClusterWrapper 在 T127 探针前的历史运行中，SourceCatalog 外层耗时 `3789.375s`，随后
RenameIndex 超过十小时仍未完成。T128 只缓存物理 range/path，服务器单模块已经证明 occurrence 阶段可从
`57.461s` 降到 `13.389s`，但它没有改变重复语义遍历和线性回退。

当前 `build_rename_index()`：

- 先完整访问 `catalog_root` 收集 `nodes`，`_module_maps()` 又完整访问一次；
- `_top_active_interfaces()` 与 `_top_active_types()` 分别完整访问 `top_root`；
- interface、struct、core declaration、occurrence、dead-source、declaration attribution 和 reference span
  等逻辑反复全量扫描同一个 `nodes`；
- `_owner_info()`、`_interface_record_for_definition()` 等在线性扫描全部 module/record；
- `_reference_attributions()` 对每个同名 token 线性检查同一 `(file, name)` bucket 的全部 reference，
  常见名字和大规模实例下可能形成平方级候选检查。

用户将同时在服务器以起始 HEAD `22cbb97`、同一 AICluster 输入运行一次冷加密，取得 T127 的十三个阶段时间。
该服务器结果是 T129 接受后的对比基线，不改变本合同，不作为本地正确性通过条件，也不授权本任务修改
SourceCatalog/PySlang 编译。

## 2. 主 Agent 固定实现计划

本任务从开始到验收只允许以下三步，不得追加缓存、SourceCatalog 或 CLI 工作：

1. 冻结有序工作集、直接索引和逐项等价合同；
2. 子 Agent 只在允许文件内实现并完成固定五条自测；
3. 主 Agent 独立复跑同一验收，核对 exact digest、actual gate、restore、Formal 和 Git 边界。

## 3. 单一目标

在一次 `build_rename_index()` 内，将 catalog/top 语义树各自最多完整访问一次，按原始 visit 顺序建立私有
有序工作集；后续声明、occurrence、dead-source 和 name-completeness 只消费工作集的有序投影。对已经具备
唯一物理 declaration/range 证据的 module、interface、record 和同名 reference 使用直接索引或有界有序
范围查询，消除按全部 module/record/reference 的重复线性回退。

优化只能改变取得相同语义事实的算法成本；候选集合、直接 PySlang target、物理范围、处理顺序、action、
reason、issue、异常、安全判据以及全部公共和持久化输出必须逐项一致。

## 4. 固定实现合同

### 4.1 有序语义工作集

- 在 `rtl_obfuscator/rename_index.py` 内新增一个最小私有 workset；每次 `build_rename_index()` 新建一次，
  禁止模块级、跨构建或磁盘缓存。
- `catalog_root` 必须恰好执行一次完整 `visit`。`top_root` 与 `catalog_root` 是同一对象时必须复用同一有序
  节点序列；不同时 `top_root` 最多执行一次完整 `visit`。
- 每个节点必须保留原始 visit ordinal；任何按 kind、owner、declaration 或用途建立的投影都必须保持这个
  相对顺序，禁止依赖 set/dict 的偶然迭代顺序改变结果。
- 工作集可以保存必要 wrapper 或提取紧凑私有事实，但不得形成第二套语义 collector；PySlang direct target、
  physical range 和现有 helper 仍是唯一权威。
- generic name-completeness 的分母不能按已知节点形状裁剪。任意节点上的 `name`、`location`、
  `declaredType.type`、`symbol/member` 和 `sourceRange` 仍必须按现有规则可参与声明或 reference 归属。
- aggregate `FieldSymbol` 必须继续通过 canonical type 递归枚举；不能假定普通 root visit 会访问字段。
- CST 仍只完整访问一次并同时服务 dead-source 与 name-completeness；本任务不得缩小 identifier token 分母。

### 4.2 直接 owner 与 record 索引

- 以规范化 `(file, start, end)` 建立 module/interface owner 索引，distinct PySlang wrapper 必须通过其自身
  physical declaration key 命中同一个 owner；禁止名称搜索或 wrapper `id()`。
- 声明建立后，以同一 physical key 和规范 category 顺序建立 record 索引；
  `_record_id_for_declaration()` 与 interface type fallback 不得遍历全部 records。
- 同一 physical key 若不能唯一映射，必须保持当前 fail-closed 结果；不得用“第一个命中”制造成功。
- 只读供应商文件、rewrite-root 外 occurrence、include-only 文件、重复 module 和 source-less owner 的现有
  firewall 与错误优先级不变。

### 4.3 同名 reference 范围索引

- `_reference_spans()` 仍只使用 PySlang `symbol/member` direct target、物理 declaration identity 和真实
  `sourceRange`，不得按文本名称猜 target。
- `(file, name)` reference 必须构造成有序范围索引或等价的离线有序查询；对同 bucket 的 T 个 token 和 R 个
  references，不得继续执行 T×R 的全 bucket 扫描。
- 最小包含范围、相同最小宽度多 owner 拒绝归属、目标将被改写时拒绝归属，这三条判据及其优先级不变。
- compact 压力测试必须记录候选检查次数，并证明 256 个同名 token/reference 的检查数小于 4096；测试不得
  使用 wall time 作为通过条件。

### 4.4 固定行为摘要

以下起始 HEAD 摘要必须保持：

```text
T108 symbols=42 occurrences=70
digest=0180e2d80e623f5677e3dbce6cf0259e9a486380d8b4ad7142c023350f23bf9f

T115 symbols=56 occurrences=125
digest=dbbc8fb76135251abcd8f87dca6e78ce3a5df7c19101e1c3907f020d8dd49a78
```

digest 投影必须包含 symbol 顺序、symbol_id、category、kind、semantic_kind、name、declaration、owner、
occurrence 顺序和 kind、impact、abi、support、reason、decision action/reason 以及 category outcomes/issues；
不能只比较汇总数量。

### 4.5 固定结构证据

目标测试必须输出单行：

```text
T129_WORKSET_EVIDENCE_JSON={"catalog_visits":1,"top_visits":<0-or-1>,"reference_candidate_checks":<int>,"t108_digest":"...","t115_digest":"..."}
```

必须满足：

- `catalog_visits == 1`；
- explicit-top 同 root fixture 的 `top_visits == 0`；独立 top root 私有单元形状至多为 1；
- 256 个同名 token/reference 的 `reference_candidate_checks < 4096`；
- 两个 digest 与 §4.4 完全相同。

不得冻结开发机秒数，也不得为通过测试硬编码 fixture/module/name/count 到产品代码。

## 5. 包含与不包含

### 包含

- 单次构建、私有、有序的 catalog/top semantic workset；
- declaration/interface/module/record 的 physical-key 直接索引；
- 同名 reference 的有序范围索引或等价非平方级查询；
- 现有 T128 range/path context 的继续复用；
- T108/T115 exact digest、结构性计数、actual compact gate、strict compile、byte-identical restore、Formal
  正例和固定功能负例。

### 不包含

- 不改变 CLI、用户命令、stderr/stdout 阶段、SourceSet 或 SourceCatalog；
- 不改变 mapping/SourceSet/orchestration/metrics/manifest/restore schema；
- 不新增 analysis-root、供应商 compiled library、PySlang snapshot、常驻进程、磁盘 cache 或缓存 CLI；
- 不按 `rewrite-root`、`-v`、目录、供应商来源或 top closure 提前删除语义候选；
- 不改变四组定义、readonly firewall、dead-source、name-completeness、range conflict 或 fail-closed 判据；
- 不修改 fixture，不增加依赖，不并行遍历，不优化 mapping、写出或 SourceCatalog；
- 不运行真实 AIClusterWrapper；服务器冷运行及接受后复测由用户环境完成。

## 6. 允许修改文件

子 Agent 只能修改：

```text
docs/tasks/T129_ordered_semantic_workset.md
rtl_obfuscator/rename_index.py
tests/test_t129_ordered_semantic_workset.py
```

需要修改其它产品、测试、fixture、文档、schema 或命令时，先在本任务“偏差或阻塞”记录并停止，不得扩大范围。

## 7. 固定验收命令

子 Agent 与主 Agent 只运行以下五条，不追加 blanket discovery、RISC Formal 或真实 AICluster：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t129_ordered_semantic_workset -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_modport_ports_are_alias_occurrences_of_interface_members \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_macro_typedef_and_conversion_shapes_are_semantically_scoped \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_unknown_cross_record_claim_preserves_the_entire_core_group \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_same_record_declaration_range_keeps_only_the_declaration \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_interface_arrays_are_root_aliases_without_anonymous_element_records \
  tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_actual_compact_gate_strict_compiles_and_restores_direct_bytes \
  tests.test_t115_name_completeness -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rename_index.py \
  tests/test_t129_ordered_semantic_workset.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T129_ordered_semantic_workset.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t129_ready_for_review=pass")'
```

Formal 固定证据由 `tests.test_t115_name_completeness.T115NameCompletenessTests.`
`test_actual_gate_formal_positive_and_fixed_functional_negative` 产生：

```text
gold: tests/fixtures/t115_name_completeness/formal.f
gate: 该测试从本次实际 RenameIndex/mapping 生成的临时 gate
top: t115_formal_top
positive required: scripts/formal_equivalence.py exit 0 and JSON formal_equivalence=pass
negative: 从同一 actual gate 只反转一个功能表达式
negative required: nonzero, unproven, and equiv_status -assert
```

## 8. 偏差或阻塞

```text
none
```

## 9. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 22cbb971b502ef4217777ed991e380d12ecc891e
start_time: 2026-09-02 11:35 Asia/Shanghai
first_command: conda run -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_modport_ports_are_alias_occurrences_of_interface_members tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_macro_typedef_and_conversion_shapes_are_semantically_scoped tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_unknown_cross_record_claim_preserves_the_entire_core_group tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_same_record_declaration_range_keeps_only_the_declaration tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_interface_arrays_are_root_aliases_without_anonymous_element_records tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_actual_compact_gate_strict_compiles_and_restores_direct_bytes tests.test_t115_name_completeness -v
allowed_files: docs/tasks/T129_ordered_semantic_workset.md; rtl_obfuscator/rename_index.py; tests/test_t129_ordered_semantic_workset.py
changed_files: docs/tasks/T129_ordered_semantic_workset.md; rtl_obfuscator/rename_index.py; tests/test_t129_ordered_semantic_workset.py
commands:
  1. conda run -n rtl_obfuscation python -m unittest tests.test_t129_ordered_semantic_workset -v
  2. conda run -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_modport_ports_are_alias_occurrences_of_interface_members tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_macro_typedef_and_conversion_shapes_are_semantically_scoped tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_unknown_cross_record_claim_preserves_the_entire_core_group tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_same_record_declaration_range_keeps_only_the_declaration tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_interface_arrays_are_root_aliases_without_anonymous_element_records tests.test_t108_pyslang_rename_index.T108RenameIndexTests.test_actual_compact_gate_strict_compiles_and_restores_direct_bytes tests.test_t115_name_completeness -v
  3. conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py tests/test_t129_ordered_semantic_workset.py
  4. git diff --check HEAD
  5. conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T129_ordered_semantic_workset.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t129_ready_for_review=pass")'
results:
  1. exit 0; 7 tests passed; T129_WORKSET_EVIDENCE_JSON={"catalog_visits":1,"reference_candidate_checks":2304,"t108_digest":"0180e2d80e623f5677e3dbce6cf0259e9a486380d8b4ad7142c023350f23bf9f","t115_digest":"dbbc8fb76135251abcd8f87dca6e78ce3a5df7c19101e1c3907f020d8dd49a78","top_visits":0}
  2. exit 0; 17 tests passed; actual T115 Formal positive exit 0 JSON formal_equivalence=pass; fixed functional negative exit 1 with unproven and equiv_status -assert
  3. exit 0
  4. exit 0
  5. pending final guard
schema_or_behavior: one private ordered workset retains visit ordinals and builds declaration/occurrence/dead-source/completeness projections in one catalog loop plus one top loop; physical module/interface owner and record lookup use normalized range keys; reference attribution uses an ordered segment-tree range index with unchanged narrowest-range, tie, rewritten-target, and fail-closed behavior; public schema and T108/T115 digests unchanged
boundaries: no additional boundary observed; SourceCatalog, CLI, fixtures, schema, dependencies and AICluster remain untouched
cleanup_candidates: none
formal_verification: PASS; gold=tests/fixtures/t115_name_completeness; gate=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t115-formal-zzdvkuf5/gate; top=t115_formal_top; positive scripts/formal_equivalence.py exit 0 JSON formal_equivalence=pass; negative actual-gate one-expression mutation exit 1 with unproven and equiv_status -assert
review_request: READY_FOR_REVIEW; implementation and fixed evidence complete; main agent must independently rerun all five commands, inspect the three-file scope and decide ACCEPTED
```

## 10. 主 Agent 验收记录

```text
status: ACCEPTED
main_result: PASS；固定三步计划和三个允许文件内完成，无范围扩张
scope_review: PASS；只修改 T129 任务单、rtl_obfuscator/rename_index.py 和目标测试；无 CLI、SourceSet、SourceCatalog、mapping/schema、fixture、依赖或安全判据改动
code_review: PASS；catalog/top 各最多一次 semantic visit；单次有序分类建立用途投影；module/interface/record 使用 physical-key 直接索引；同名 reference 使用 O((T+R) log T) 离线 segment-tree 查询；generic completeness 保留任意 named、symbol/member 和 declaredType carrier，aggregate fields 仍递归枚举
decision_digest: PASS；T108 42 symbols/70 occurrences，SHA-256 0180e2d80e623f5677e3dbce6cf0259e9a486380d8b4ad7142c023350f23bf9f；T115 56 symbols/125 occurrences，SHA-256 dbbc8fb76135251abcd8f87dca6e78ce3a5df7c19101e1c3907f020d8dd49a78；逐项投影与起始 HEAD 完全一致
workset_evidence: PASS；catalog_visits=1，explicit-top same-root top_visits=0，256 个同名 token/reference 的 reference_candidate_checks=2304；distinct top root 测试为 1；范围索引与 deterministic naive oracle 一致
target_result: PASS；tests.test_t129_ordered_semantic_workset，Ran 7 tests，exit 0
compatibility_result: PASS；固定 T108/T115 行 Ran 17 tests，exit 0；actual compact gate strict compile、range audit、public CLI 和 byte-identical restore 均通过
py_compile: PASS；精确第 7 节命令 exit 0
git_diff_check: PASS；git diff --check HEAD exit 0
ready_for_review_guard: PASS；接受前输出 t129_ready_for_review=pass
formal_verification: PASS；T115 actual gate 正例 exit 0，JSON formal_equivalence=pass，top=t115_formal_top；同 gate 固定 1'b0 -> 1'b1 功能负例 exit 1，evidence=unproven; equiv_status -assert
accepted_by: Main Agent Codex，2026-09-02 Asia/Shanghai
```

## 11. 验收后的唯一下一步

T129 接受并推送后，只使用用户返回的 `22cbb97` AICluster 冷运行数据与 T129 同输入复测数据比较七个
RenameIndex 子阶段。是否继续优化 SourceCatalog 或设计紧凑事实快照，必须在 T129 接受后另行分析；本任务不
预先授权下一实现。
