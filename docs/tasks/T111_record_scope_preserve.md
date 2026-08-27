# T111：把绑定失败的爆炸半径从核心组降为单条记录

- 状态：`READY`
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
status: READY
starting_head: 992980c
```
