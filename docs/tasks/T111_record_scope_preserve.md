# T111：把绑定失败的爆炸半径从核心组降为单条记录

- 状态：`ACCEPTED`
- 主 Agent：Claude Fable 5
- 起始 HEAD：`992980c`（T110 已 `ACCEPTED`，T109 已 `ACCEPTED`，T108 保持 `BLOCKED`）
- 任务类型：`rename_index.py` 的保留策略事务边界收缩 + 宏位置还原后锚定
- 依据：[`T110 §15`](T110_core_group_binding_fixes.md) 的服务器实测、
  [`token_first_binding.md`](../development/architecture/token_first_binding.md) §2

## 0. 为什么现在做这件事

T110 的服务器数据给出了决定性证据：

```text
struct: candidate=541  rename=0  preserve=541
  3 个真实根因（FieldSymbol occurrence 绑不上）
541 个组级传播 issue
```

**3 个未绑定 token 清零了 541 条记录，其中 538 条绑定完好。**

T069–T108 的 22 轮打地鼠说明：真实工程里总会有下一个未知形状。只要爆炸半径是"全设计同类别"，
无论修掉多少形状，一个残留就让整组回到 0。收缩半径是终止该循环的唯一办法，
也是达成"四组稳定改名不报错"的必要条件。

## 1. 单一目标

把 `_apply_group_binding_issues` 的传播范围从**核心组**收缩为**单条记录**：
绑定证据不足的记录自己保留，同组其他已完整证明的记录继续改名。
并让 `_member_access_range` 在宏位置上先还原再锚定，而不是直接放弃。

## 2. 冻结的两项修改

### 2.1 逐记录保留取代组级传播（主项）

现状 `_apply_group_binding_issues` 的逻辑是：某核心组只要出现一条不在
`{selected_top_boundary, outside_top_closure, macro_origin_conflict}` 内的 reason，
就把**该设计中该组所有 eligible 记录**改为 preserve。

冻结做法：`source_binding_incomplete` 只保留**产生该 issue 的那条记录**。
`category_outcomes.issues` 仍记录具体 file/start/message，不得丢失定位信息。

安全性论证（必须在实现中保持，不得削弱）：

- 改名安全的约束是"改了声明就必须改全部引用"，这是**单条记录**内的约束；
- 跨记录的耦合只有两处，且都已被单独处理：共享物理 range 由 `_resolve_range_claims`
  处理（`macro_origin_conflict` 逐对象、未知跨记录冲突仍按现状处理）；
  单个 aggregate 的字段完整性由 `_register_structs` 的 per-aggregate 事务处理；
- 因此把传播降到单条记录**不引入新的不安全面**。

**本任务不改动** `_resolve_range_claims` 的跨记录冲突处理，也不改动 `_register_structs`
的 per-aggregate 事务。这两处的收缩另议。

### 2.2 宏位置先还原再锚定

现状 `_member_access_range` 的守卫：

```python
if manager.isMacroLoc(start) or manager.isMacroLoc(end):
    return None
```

守卫的理由正确——虚拟位置不能做偏移算术——但放弃得过早。T110 §15.1 实测确认，
StCache 上剩余的 3 个根因全部是宏参数内的成员访问，物理 token 确实存在于调用点：

```text
`ASSERT_..._IF(..., mshr_ff_rdat.org_retry_info.cmd[5] , ...)
`ASSERT_..._IF(LAST_CHECK, ..., (^response_fifo_winfo.drw_cmd[6:5]))
```

冻结做法：`start` 或 `end` 为宏位置时，各经 `SourceManager.getFullyOriginalLoc` 还原为物理位置，
**还原后**再执行既有流程。还原后仍必须逐项通过既有守卫：跨 buffer 返回 `None`、
`begin <= start.offset` 返回 `None`、字节不匹配返回 `None`。
禁止在宏路径上放宽字节校验。

还原后若两条记录争用同一物理 range（宏体被多次展开），仍由 `_resolve_range_claims`
按既有 `macro_origin_conflict` 逐对象处理——本任务不得绕过该检测。

## 3. 不包含的内容

- 不改变四个公开 category、`--encryption-rate`、mapping schema 2、SourceSet 语义、PySlang 编译配置；
- 不改动 `_resolve_range_claims` 的跨记录冲突策略，不改动 `_register_structs` 的 per-aggregate 事务；
- 不实现层次引用前缀（interface 实例仍以 `hierarchical_prefix_unsupported` 保留）；
- 不实现 `NamedType` typedef 类型引用、`NamedParamAssignment`、`HierarchyInstantiation`；
- 不实现 T109 探测器的逐符号完整性判据；
- 不新增名称搜索、文本扫描、正则解析或第二套 owner 推断；
- 不运行 RISC-V-Vector Formal，不使用 blanket `unittest discover`。

## 4. 允许修改

- `rtl_obfuscator/rename_index.py`
- `tests/test_t111_record_scope_preserve.py`（新增）
- `tests/fixtures/t111_record_scope_preserve/**`（新增）
- `tests/test_t108_pyslang_rename_index.py`、`tests/test_t110_binding_fixes.py`
  （仅在既有断言因本次改动而必须调整时同步；调整必须逐条在任务记录中说明理由，不得放宽）
- 本任务单、`docs/development/architecture/token_first_binding.md`

## 5. 固定 fixture

新增 `tests/fixtures/t111_record_scope_preserve/design.f`，其 `design.sv` 必须同时包含：

- 同一核心组内**一条绑定不足的记录**与**多条绑定完好的记录**，用于证明只有前者被保留；
- 宏参数内的成员访问，含嵌套成员 + bit select 与 成员 + part select 两种，
  复现 T110 §15.1 的两个真实形状；
- 一处宏体被多次展开、导致两条记录争用同一物理 range 的情形，
  用于证明 `macro_origin_conflict` 仍按逐对象生效、未被本次改动绕过；
- 一个 Yosys 可读的 Formal cone。

既有 `tests/fixtures/t108_pyslang_rename_index/boundary.f` 断言"未知绑定导致整组 struct 保留"，
该断言在本任务后**必然改变**。必须改为断言"只有产生 issue 的记录被保留，同组其他记录仍改名"，
并在任务记录中说明这是策略变更的预期结果，而非放宽。

## 6. 机器可验收结果

本地 fixture 上 `--category all` 必须满足：

- 一条记录的 `source_binding_incomplete` **只保留该条记录**；同组其他 eligible 记录 `rename`；
- `category_outcomes.issues` 仍带具体 file/start/message，定位信息不丢失；
- 宏参数内的两种成员访问形状均被绑定并改名；
- 宏体多次展开的争用仍报 `macro_origin_conflict` 且逐对象保留，未被绕过；
- 四组 `category_outcomes` 均 `rename > 0`；
- `strict_compile_passed=true`、`restored_byte_identical=true`；range audit 无重复、重叠、越界；
- actual renamed gate 的 Formal 正例 exit 0 且 `formal_equivalence=pass`；
  固定功能负例 strict compile 通过但 Formal 非零，含 `unproven` 或 `equiv_status -assert`。

## 7. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t111_record_scope_preserve tests.test_t110_binding_fixes \
  tests.test_t108_pyslang_rename_index tests.test_t108_public_core_flow \
  tests.test_public_cli tests.test_mapping_vnext tests.test_rewrite_vnext \
  tests.test_orchestration_vnext tests.test_restore_vnext -v

conda run -n rtl_obfuscation python -m unittest tests.test_binding_coverage -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rename_index.py tests/test_t111_record_scope_preserve.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T111_record_scope_preserve.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t111_ready_for_review=pass")'
```

`tests.test_t111_record_scope_preserve` 必须实际调用 `scripts/formal_equivalence.py` 完成正负例，
并给出 gold、actual gate、top、命令、退出码与 JSON。判决行必须直接读 `OK` / `FAILED`，
不得用管道掩盖退出码。

## 8. 服务器验收（本任务的第二半）

```sh
export PROJ=/home/lufengchi/workspace/ChipPlatform
OUT=/home/lufengchi/workspace/test/stcache_all_t111_001

python rtl_encrypt.py \
  --filelist "$PROJ/aic_ss/src/stcache/StCache.f" \
  --top StChCore \
  --category all \
  --include-dir "$PROJ/common/src/StLib/common" \
  --include-dir "$PROJ/common/src/StLib/impl_template/tsmc4" \
  --output-dir "$OUT"
```

通过条件（即用户的最低要求）：

- 无 `REFUSED_ATOMIC`；
- `strict_compile_passed` 与 `restored_byte_identical` 均为 `true`；
- **四组均 `rename > 0`，其中 `struct` 由 T110 的 0 变为大于 0**；
- preserve 原因只允许 `selected_top_boundary` / `outside_top_closure` /
  `macro_origin_conflict` / `hierarchical_prefix_unsupported` /
  `source_binding_incomplete`（后者现在只影响自身记录）；不得出现未解释的新原因；
- mapping schema 2，range audit 无重复、重叠或越界。

预期量级参考：T110 服务器数据显示 struct 有 541 个候选、3 个真实根因。
按逐记录保留，struct 改名数应接近 541；§2.2 生效后 3 个根因也应消失。
该数字是参考不是硬条件——硬条件是"rename > 0 且无未解释原因"。

## 9. Formal verification

本任务产生改写 RTL，必须在本地 compact fixture 上完成一个 actual-gate 正例与一个固定功能负例。
StCache 规模的 Formal 不属于本任务；第 8 节的 strict compile 与 byte-identical restore 是硬条件。

## 10. 执行记录

```text
status: ACCEPTED
starting_head: 5652236
```

- 开始时间：2026-08-27
- 合同 `起始 HEAD` 写作 `992980c`（T110 交付时的 HEAD）；本任务实际开始于 `5652236`
  （即冻结 T111 的那次提交），`git status` 为干净工作区，与允许文件无用户改动重叠。
- 工具环境：本沙箱 `conda run -n rtl_obfuscation` 报 `__conda_exe: permission denied`，
  改用同一环境的解释器绝对路径 `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python`。
- 允许文件：`rtl_obfuscator/rename_index.py`、`tests/test_t111_record_scope_preserve.py`（新增）、
  `tests/fixtures/t111_record_scope_preserve/**`（新增）、
  `tests/test_t108_pyslang_rename_index.py`、`tests/test_t110_binding_fixes.py`（仅必需同步）、
  本任务单、`docs/development/architecture/token_first_binding.md`。
- 首条命令（baseline，改代码前）：
  `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python -m unittest tests.test_t110_binding_fixes tests.test_t108_pyslang_rename_index -v`

### 10.1 交付记录补全说明

实现子 Agent 在写完产品代码、fixture 与测试后被外部中断（本会话中子 Agent 已多次因
API 鉴权 403 终止），未能自行跑完门禁并置 `READY_FOR_REVIEW`。
主 Agent 检查磁盘产物确认实现完整，随后**独立执行全部门禁**并据实测证据补全本记录。
补全的内容全部来自主 Agent 亲自运行的命令输出，非采信子 Agent 自报。

changed_files: rtl_obfuscator/rename_index.py；tests/test_t111_record_scope_preserve.py（新增）；
  tests/fixtures/t111_record_scope_preserve/{design.f,design.sv,formal.f,formal_cone.sv,t111_macros.svh}（新增）；
  tests/test_t108_pyslang_rename_index.py（§5 要求的断言改写）；
  docs/tasks/T111_record_scope_preserve.md；docs/development/architecture/token_first_binding.md
formal_verification: PASS（见 §11）

## 11. 主 Agent 独立本地验收记录

```text
reviewed_at: 2026-08-27
main_gate_1: exit 0；Ran 55 tests；OK（直接读 OK/FAILED 判决行，未经管道掩盖）
main_gate_2: exit 0；tests.test_binding_coverage Ran 15 tests；OK
main_gate_3: exit 0；py_compile
main_gate_4: 首跑 exit 2（任务单文件末尾多一空行，子 Agent 中断所致）；主 Agent 去除后 exit 0
main_gate_5: exit 0；t111_ready_for_review=pass

main_formal_positive: 真实 actual gate；exit 0；formal_equivalence=pass
main_formal_negative: exit 1；evidence "unproven; equiv_status -assert"
formal_freshness: 临时目录 t111-formal-8t67h7dc，与 T110 各轮均不同，确认真实重跑
skip_check: tests/test_t111_record_scope_preserve.py 内 skipTest/@unittest.skip 计数为 0

main_cli_verification（主 Agent 独立跑 --category all）:
  PASS_PARTIAL；strict_compile_passed=true；restored_byte_identical=true
  rename=59 preserve=14 unsupported=2
  signals    cand=19 rename=17 preserve=0  unsup=2   macro_origin_conflict
  ports      cand=40 rename=29 preserve=11 unsup=0   selected_top_boundary
  interface  cand=8  rename=6  preserve=2  unsup=0   hierarchical_prefix_unsupported
  struct     cand=8  rename=7  preserve=1  unsup=0   source_binding_incomplete
  程序化断言"四组均 rename>0" = True

main_核心行为验证（本任务的单一目标）:
  source_binding_incomplete 记录数 = 1，同时仍有 rename 记录 59 条
  → 一条记录的绑定不足只保留该条记录，同组其余 7 条 struct 记录照常改名。
    T111 之前该 issue 会让全部 8 条一起阵亡。爆炸半径已由 category 收缩为 record。
  macro_origin_conflict 记录数 = 2 → 共享物理 range 检测未被绕过。

main_code_review:
  - `_apply_group_binding_issues` 的类别级升级循环已删除，改为逐记录赋值；
    docstring 记录了安全性论证与 541/538 的实证依据。
  - `_resolve_range_claims` 与 `_register_structs` 的定义未出现在 diff 中，§3 边界守住；
    `test_unknown_cross_record_claim_preserves_the_entire_core_group` 仍在且通过，
    证明未知跨记录冲突仍保留组级回滚。
  - 未引入 re./regex/readlines 等禁止模式。
  - T108 断言改写经逐条复核为**加强**而非放宽：
      旧：all(preserved and reason==source_binding_incomplete for symbol in structs)
      新：致因记录仍 fail-closed；preserved 名字集合精确等于 {"boundary_macro_struct_t"}；
          兄弟记录 support=="eligible" 且 reason is None；rename/preserve/unsupported 精确计数；
          新增断言"详细 FieldSymbol 诊断（semantic_kind/name/file/detail）必须存活"；
          新增断言"任何 issue 都不得指向从未致因的记录"。
    每处均带注释标明是 T111 §2.1 策略变更。

main_local_result: PASS
server_gate: PENDING —— §8 的 StCache 验收是本任务第二半，未通过前不得设 ACCEPTED
delivery_note: 为使服务器能 pull，主 Agent 在 server_gate 之前提交推送；这是交付而非验收。

## 12. 服务器验收通过与 ACCEPTED（主 Agent，2026-08-27）

服务器在 `ebefc94` 上运行第 8 节命令，输出目录 `stcache_all_t111_001`：

```text
rename=5931  preserve=1153  unsupported=18  modified_tokens=21922
加密率 0.38336（13152 / 34307 行）
加密类型 4：signals, ports, interface, struct        ← 用户最低要求达成
strict_compile_passed=true  restored_byte_identical=true
occurrence_coverage=1.0  symbol_coverage=1.0  plaintext_leakage_rate=0.0
mapping schema 2；无 REFUSED_ATOMIC

category_outcomes 与 preserve 原因直方图：
  signals    cand=3184 rename=2775 preserve=409 unsup=0   409 outside_top_closure
  ports      cand=3241 rename=2636 preserve=587 unsup=18  422 outside_top_closure
                                                          165 selected_top_boundary
                                                           20 macro_origin_conflict
  interface  cand=136  rename=113  preserve=23  unsup=0    23 hierarchical_prefix_unsupported
  struct     cand=541  rename=407  preserve=134 unsup=0   134 outside_top_closure
```

### 12.1 逐条核对第 8 节通过条件

| 条件 | 结果 |
| --- | --- |
| 无 `REFUSED_ATOMIC` | 通过（`PASS_PARTIAL`） |
| `strict_compile_passed` 与 `restored_byte_identical` 均 true | 通过 |
| **四组均 `rename > 0`，struct 由 0 变为大于 0** | 通过（struct 407） |
| preserve 原因只允许 5 种，无未解释新原因 | 通过，且**只出现 4 种** |
| mapping schema 2、range audit 无重复/重叠/越界 | 通过 |

**`source_binding_incomplete` 计数为 0** —— §2.2 的宏位置还原完全解决了 T110 遗留的 3 个根因，
全设计已无绑定失败。

### 12.2 两处与预期不同、结果更好的地方

1. struct 的 134 条保留**不是** `source_binding_incomplete`，而是 `outside_top_closure`。
   主 Agent 在服务器数据前的推测（"爆炸半径掩盖了逐记录失败数"）**被推翻**：
   这些 typedef 只是不在 StChCore 的活跃类型闭包内，属既有策略边界，本应保留。
2. `ports rename=2636 / preserve=587 / unsupported=18` 与 T108 重构**之前**的历史基线
   （见 `stcache_core_category_stability.md`）**完全相同**。T108 造成的 ports 能力回退已彻底修复，
   且新架构复现了旧架构的逐项计数。

### 12.3 验收结论

`main_result: ACCEPTED`

本地五条门禁与服务器门禁全部通过；主 Agent 独立复跑，未采信子 Agent 自报。
T111 的单一目标（爆炸半径 category → record）在本地与真实工程上均得到验证。

### 12.4 上线前仍未闭合的一项风险（不属于 T111 范围）

主 Agent 审查 `metrics_vnext.py:_validate_gate_edits` 后确认：
`plaintext_leakage_rate` 只遍历 `execution.edits`，逐个验证 gate 字节等于新名而非旧名。
它证明"计划的编辑都执行了"，**不证明 gate 中没有残留旧名**。
`occurrence_coverage` 同理，是已识别 occurrence 的覆盖率，不是全部文本出现的覆盖率。

因此以下失败模式在当前证据下**未被排除**：某个引用从未被识别 → 声明改名而该引用保留旧名 →
在 SystemVerilog 缺省 `default_nettype` 下，端口连接实参位置的未声明标识符会变成隐式 wire →
**strict compile 干净通过但功能错误**。

StCache 未跑 Formal（其 interface/aggregate 语法 Yosys 难以完整解析，见 `future_work.md`）。
建议在上线前用一次只读的"gate 残留旧名扫描"闭合该风险，归 T112。
