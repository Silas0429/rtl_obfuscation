# T143：FULL 分类与端口声明事实复用

- 状态：`ACCEPTED`
- 起始分支 / HEAD：`main@10cecac8afce2fcab979f524b41e6cad314ea600`
- 负责人：主 Agent（边界、冻结测试、独立验收）/ 实现子 Agent（仅本任务）
- 前置：T142 ACCEPTED，已提交并推送 origin/main。
- 计划：[`full_rename_index_performance_plan.md`](../development/full_rename_index_performance_plan.md)
- 验收类型：rewrite/mapping；复用 T142 compact actual-gate 正负 Formal。

## 单一目标

减少同一次 RenameIndex 构建中的重复事实解析：同 catalog/top tuple 的 declared-type alias 判断，
以及同次端口登记中的成功 declaration。保持完整遍历、错误重试与未来规则扩展能力。

必读 AGENTS.md、docs/tasks/README.md、refactor_subagent_protocol.md、docs/formal_verification.md、
docs/systemverilog_renaming_table.md、本计划。主 Agent 冻结 `tests/test_t143_workset_fact_reuse.py`，
也不得修改 T142 或已有测试。

## 实现边界

### 同 root 分类

- 始终完整、有序地遍历 catalog 和 top 投影；`collect` 对相同实际 root 的一次 visit 不变。
- 保持 top 分类谓词唯一来源；不得增加 `top_candidates`、另一份节点类型名单或预筛选。
- 只在 `self.top is self.catalog` 时按 tuple 位置复用 alias bool；不缓存准入、owner 或 target。
- 仅当 `declaredType` 和 `.type` 两层属性都读取成功才保存事实。属性缺失、AttributeError、
  其他 Exception 都不能被缓存为 False；失败时 top 阶段按原 `_safe_attr` 路径重新读取。
  成功且 type 为 None 可作为已知非 alias；外层 declaredType 为 None 不满足两层成功。
- 允许一个小型私有 getter 辅助函数返回 declared type 及成功标记；不改通用 `_safe_attr`。
  不依赖已知 node class，不形成持久化或跨 build cache。沿用单次构建内语义结构不变的前提。
- `isInterface`、conversion `.type` 仍在原 top 分类阶段读取，不能提前改变访问顺序。
- 不同 root 和不同长度的 top 必须完整读取，不能 zip 截断或复用另一 root 的位置。

### 本次端口登记

- 仅复用 `_register_core_declarations` 预扫描已成功得到的 declaration；失败原顺序重试。
- 可使用强引用 + id/is 身份核对的局部字典；函数返回即释放，不按名字或物理范围合并实例。
- owner、category、support、reason、targets、internalSymbol 都继续逐节点、逐调用计算。
- `_try_declaration_range` / `_declaration_range` / typed-token 与 semantic-location 规则不改。
  candidates 参数只影响失败诊断；成功缓存不可吞失败或合并诊断。

子 Agent 允许修改：

```text
rtl_obfuscator/rename_index.py
docs/development/project_structure.md
docs/tasks/T143_workset_fact_reuse.md
```

仅限上述两处及必要的小辅助逻辑；project_structure 仅记本次事实寿命、失败重试与扩展性。
不改 T142 补证算法、SourceCatalog、Mapping、全局名称集合、公共 schema、类别、准入、gate、restore、
Formal，不引入通用缓存、依赖、持久化或新扩展框架。主 Agent 独立负责计划、测试及最终性能报告。

旧 `/tmp/full-explore-workset-XWH0u5/prototype.py` 只供参考；其 top_candidates 和失败 False 复用
已被只读审查否定，不能照搬。不能将动态源码替换或 monkeypatch 加入产品。

## Baseline（唯一命令）

记录 HEAD/status，READY→IN_PROGRESS 后执行：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t143_workset_fact_reuse tests.test_t142_pending_name_proofs -v
```

T143 预期仅 5 个性能工作量断言失败（成功属性两次读取、成功端口重复解析）；正确性、失败重试、
混合顺序、不同 top 节点、T142 全部应通过。主 Agent 已在临时草稿确认此基线。

## 冻结验收（五条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t143_workset_fact_reuse tests.test_t142_pending_name_proofs -v

conda run -n rtl_obfuscation python -m unittest tests.test_t128_rename_index_range_cache tests.test_t129_ordered_semantic_workset tests.test_t141_semantic_name_reuse -v

conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py tests/test_t143_workset_fact_reuse.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T143_workset_fact_reuse.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t143_ready_for_review=pass")'
```

第一条包含 T142 正常完整流程：确定性 Mapping、实际改名 gate、strict compile、byte restore，
`scripts/formal_equivalence.py` 对 `proof_top` seq=5 正例 exit0/pass，以及实际 gate XOR 常量
改一 bit 的功能负例非零/unproven/equiv_status -assert。必须记录实际路径、精确命令、退出码、JSON。
port mock 只证明缓存层顺序；typed-token 优先级由未改 helper 与已有真实回归共同保护，不能夸大。
不运行 RISC、blanket discovery、identity Formal 或历史全量验收脚本。

## 子 Agent 执行记录

- 开始时间：2026-09-15 06:27:45 UTC。
- starting_head：`main@10cecac8afce2fcab979f524b41e6cad314ea600`，与 origin/main 同步。
- 初始工作区：仅主 Agent 预置的本合同与 `tests/test_t143_workset_fact_reuse.py` 未跟踪；实现文件
  与结构文档无已有修改。冻结测试 SHA256：
  `78c7a50fa8e62f5ae1422a9a47a257a8cec075d446269262be5e8a0afc255c7f`。
- 已读 AGENTS、任务流程、子 Agent 协议、计划、Formal 与重命名类别表；仅本合同为活动任务。
- 允许文件：`rtl_obfuscator/rename_index.py`、`docs/development/project_structure.md`、本合同。
- baseline：`conda run -n rtl_obfuscation python -m unittest tests.test_t143_workset_fact_reuse tests.test_t142_pending_name_proofs -v`，
  exit 1，20 tests / 5 expected failures（成功 alias 读取 / 成功端口解析次数）；其他正确性、错误重试、
  不同 top 及 T142 8 tests 全部通过，符合冻结基线。
- 实现采用 getter 缺省 sentinel 区分普通属性缺失，避免在大量不含 declaredType 的节点上主动抛异常；
  两层任一缺失或读取异常仍不得缓存，top 原路径重试。未改变合同范围。
- changed_files：`rtl_obfuscator/rename_index.py`、`docs/development/project_structure.md`、本合同；
  预置 T143 测试 SHA256 未变，T142 及既有测试无修改。
- schema_or_behavior：无公共 schema、类别、准入变化。alias 事实仅保存在 `__post_init__` 的局部列表，
  只供相同 catalog/top tuple 按位置读取；完整 top 分类保持单一规则。成功端口物理声明仅保存在
  本次 `_register_core_declarations` 的强引用字典，owner/category/support/reason/targets 照常计算。
- boundaries：沿用单次构建内语义结构稳定前提；缺失 / getter 异常均不形成 False 事实；不同 root
  不复用位置。port mock 只证明复用层的工作量、实例区分与事件顺序；typed-token 和 semantic-location
  helper 未修改，其优先级由既有真实回归保护。本任务未做服务器同输入性能重跑，最终串行测量由主
  Agent 负责。无 RISC、blanket discovery、identity Formal 或历史全量验收。
- cleanup_candidates：无。

### 增量验证

先实现分类，再实现端口。以下精确命令分别 exit 0，8 tests OK 与 3 tests OK：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t143_workset_fact_reuse.T143WorksetFactReuseTests.test_successful_facts_reused_without_filtering_full_top_iteration tests.test_t143_workset_fact_reuse.T143WorksetFactReuseTests.test_missing_or_failed_outer_fact_is_retried tests.test_t143_workset_fact_reuse.T143WorksetFactReuseTests.test_missing_or_failed_inner_fact_is_retried tests.test_t143_workset_fact_reuse.T143WorksetFactReuseTests.test_same_nodes_new_build_recomputes_facts tests.test_t143_workset_fact_reuse.T143WorksetFactReuseTests.test_distinct_and_absent_top_do_not_share_facts tests.test_t143_workset_fact_reuse.T143WorksetFactReuseTests.test_mixed_success_and_retry_keep_positional_facts_aligned tests.test_t143_workset_fact_reuse.T143WorksetFactReuseTests.test_distinct_top_new_nodes_and_different_length_are_not_truncated tests.test_t143_workset_fact_reuse.T143WorksetFactReuseTests.test_top_specific_getters_keep_late_order -v

conda run -n rtl_obfuscation python -m unittest tests.test_t143_workset_fact_reuse.T143WorksetFactReuseTests.test_port_success_reuse_does_not_merge_same_physical_instances tests.test_t143_workset_fact_reuse.T143WorksetFactReuseTests.test_port_failed_prescan_retries_with_original_issue_order tests.test_t143_workset_fact_reuse.T143WorksetFactReuseTests.test_port_policy_selection_owner_and_targets_recomputed_each_call -v
```

### 冻结验收结果

精确命令为上文冻结五条，执行结果：

1. T143 + T142：exit 0，20 tests OK，含完整决策、确定性 Mapping、实际 gate strict compile、byte restore
   及下方 compact Formal；耗时 1.116s。
2. T128 + T129 + T141：exit 0，21 tests OK，耗时 0.497s。T108 决策 digest
   `0180e2d80e623f5677e3dbce6cf0259e9a486380d8b4ad7142c023350f23bf9f`；T115 决策 digest
   `dbbc8fb76135251abcd8f87dca6e78ce3a5df7c19101e1c3907f020d8dd49a78`；T141 Mapping digest
   `e4bea7aee2502f833053859bf9b34a21adf81a17530aaf5faa18f9ae3b2831da`。
3. py_compile：exit 0，无输出。
4. diff check：exit 0，无输出。
5. READY_FOR_REVIEW 守卫：exit 0，`t143_ready_for_review=pass`。

review_request：五条冻结验收通过，交由主 Agent 独立复跑、性能测量与验收；子 Agent 未提交、未推送。

### Formal verification

- formal_verification：PASS；由冻结第一条测试在 Conda 环境中使用该环境的 `sys.executable` 调用。
- gold：`/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-82zxw7y4/source/design.sv`。
- gate：`/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-82zxw7y4/gate/design.sv`。
- top：`proof_top`；seq：5。gate 具有实际名称替换，测试断言 gate 字节与 gold 不同。
- positive 实际子进程命令：

```sh
/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-82zxw7y4/source/design.sv --gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-82zxw7y4/gate/design.sv --top proof_top --seq 5
```

- positive exit 0，JSON：

```json
{"formal_equivalence":"pass","gate":"/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-82zxw7y4/gate/design.sv","gold":"/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-82zxw7y4/source/design.sv","seq":5,"top":"proof_top"}
```

- negative：在实际 gate 中仅将 XOR 常量 `4'b1010` 改为 `4'b1011`；实际子进程命令：

```sh
/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-82zxw7y4/source/design.sv --gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-82zxw7y4/negative.sv --top proof_top --seq 5
```

- negative exit 1，测试同时断言输出包含 `unproven` 和 `equiv_status -assert`；测试证据 JSON
  `{"fixed_functional_negative":"rejected"}`（不是 Formal 成功 JSON）。临时文件随测试结束清理，
  主 Agent 通过冻结第一条重新生成自己的 actual gate 并独立验证。

## 主 Agent 验收

2026-09-15 主 Agent 在正式 READY_FOR_REVIEW 后独立重跑全部五条冻结命令：

- 状态守卫 exit0，`t143_ready_for_review=pass`；T143 测试 SHA256
  `78c7a50fa8e62f5ae1422a9a47a257a8cec075d446269262be5e8a0afc255c7f` 未变；T142 冻结 SHA 也未变。
- 目标测试 exit0，20 tests / 1.122s；回归 exit0，21 tests / 0.521s。
- py_compile、`git diff --check HEAD` exit0。主 Agent 与独立只读审查 Agent 均确认没有额外类型
  筛选、跨 root / build 缓存或准入结果缓存；原 canonical helpers 和 T142 补证算法未改。
- 完整 Mapping/gate、严格编译、逐字节恢复通过。属性缺失/异常恢复、混合成功失败位置、不同 top
  节点和长度、完整遍历、晚序 getter、跨调用 owner/target/support/reason 更新均通过。

Main actual-gate Formal 由第一条测试独立生成并执行，精确证据如下：

```text
gold: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-zhgt1tr3/source/design.sv
gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-zhgt1tr3/gate/design.sv
negative: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-zhgt1tr3/negative.sv
top: proof_top; seq: 5
positive command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-zhgt1tr3/source/design.sv --gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-zhgt1tr3/gate/design.sv --top proof_top --seq 5
positive exit: 0
positive JSON: {"formal_equivalence":"pass","gate":"/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-zhgt1tr3/gate/design.sv","gold":"/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-zhgt1tr3/source/design.sv","seq":5,"top":"proof_top"}
negative command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-zhgt1tr3/source/design.sv --gate /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t142-full-zhgt1tr3/negative.sv --top proof_top --seq 5
negative exit: 1; unproven / equiv_status -assert detected
negative evidence JSON: {"fixed_functional_negative":"rejected"}
```

临时 Formal 文件随 unittest 清理；原始输出保存在 `/tmp/full-production.JTQGLB/t143-main.stdout`
及 `.stderr`，回归同目录 `t143-regression.stdout` / `.stderr`。未运行 RISC 或 blanket discovery。
最终生产代码串行对照与审计通过：72 个核心正式样本的完整决策、确定性 Mapping/gate 哈希一致；
24 个公开 CLI 进程成功，两版本三样例各一次公开 decrypt（6 次）逐字节还原成功。8 个独立内存
进程成功，未显示明显内存放大。23 个基线产品 / CLI / digest helper Git blob 已核对原提交。

相对起点 1b9feb7，三类公开 CLI 样例耗时下降 6.8%～22.8%；核心样例下降 6.7%～24.7%。
最终源码 SHA256 为 `cfb75b05310bdef7e3679d5ad34d8f4d18a416c5482b55fe8ae02b4c717891e2`，
计时前后未变。完整数字、内存波动、命令与服务器证据边界见计划的最终实测节。

主 Agent 接受 T143，两步实现及扩展性验收完成。未为保留探索原型的速度牺牲完整遍历或失败重试。
