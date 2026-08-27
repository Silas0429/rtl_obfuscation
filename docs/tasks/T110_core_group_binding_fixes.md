# T110：四核心组稳定改名的三处绑定修复与目标身份统一

- 状态：`READY_FOR_REVIEW`
- 主 Agent：Claude Fable 5
- 起始 HEAD：`0e28030`（T109 已 `ACCEPTED`，T108 保持 `BLOCKED`）
- 任务类型：`rename_index.py` 内的 occurrence 绑定修复 + 目标身份口径统一
- 依据：[`token_first_binding.md`](../development/architecture/token_first_binding.md)、
  [`T108 §15`](T108_pyslang_rename_index.md) 的实测更正、[`T109`](T109_binding_coverage_probe.md) 的服务器测量

## 0. 产品目标（用户 2026-08-27 明确）

本项目服务于对外售卖 IP 的混淆需求，**不要求完全加密**：`--encryption-rate` 本就支持部分加密。
最低要求是 `signals`、`ports`、`interface`、`struct` 四组**稳定改名且不报错**。

因此本任务的目标不是提升覆盖率，而是让四组各自都有**可证明正确的真实改名**，
无法证明的对象逐个保留并给出可解释原因。覆盖率是后续任务的事。

## 1. 单一目标

消除服务器 StCache 上导致 `ports/interface/struct` 三组 `rename=0` 的三处 occurrence 提取缺陷，
并把目标身份口径从 Python 对象身份统一为物理声明位置。修复后四组在 StCache 上均有真实改名，
且 `strict_compile_passed` 与 `restored_byte_identical` 保持 `true`。

## 2. 冻结的四项修改

### 2.1 目标身份必须是物理声明位置（前置项）

`_record_for_semantic_target` 等一切按目标标识记录的地方，必须以目标的**物理声明位置**为身份，
不得依赖 Python 对象身份。elaboration 会为同一物理声明产生多个对象：T109 实测
`eb_one_slot.sv` 被实例化 4 次时，同一源码 token 被判为"4 个所有者竞争"。
该项修好后，探测器口径下 in-scope 覆盖由 70.75% 升至 92.47%、歧义由 1294 降为 0。

### 2.2 Ports —— 命名端口连接标签不得按下标配对

现状：`_collect_occurrences` 把 `syntax.connections` 与 `node.portConnections` 直接 `zip`。
T109 实测两个列表顺序不一致，且 `PortConnection` 只暴露 `expression / ifaceConn / port`，
没有 `syntax` 也没有 `sourceRange`：

```text
端口声明顺序 a_first, b_second, c_third；实例化写 .c_third / .b_second / .a_first
  SOURCE order   : ['c_third', 'b_second', 'a_first']
  SEMANTIC order : ['a_first', 'b_second', 'c_third']
```

冻结做法：对每个 `NamedPortConnectionSyntax`，取其 `.name` token，在**该实例自身
`portConnections` 的端口集合内**解析目标端口，并用既有 `_range_for_token` 做字节校验。

这不是"按名称查找 owner"：owner（被实例化的 definition）已由 PySlang 确定，
而命名端口连接**在语言定义上就是按名字绑定的**，读取该名字是执行语言规则而非猜测。
定位范围限于该实例自己的端口集合，不跨设计搜索。

`.*` 隐式连接与位置连接没有标签 token，不产生 occurrence；`.name()` 空实参仍有标签，需改写。

### 2.3 Interface —— modport 限定的 port header 取错了属性

现状：`InterfacePortHeaderSyntax` **没有 `dataType` 属性**，而代码只试 `header.dataType`
与 `port_parent.type`，两者皆 `None`，于是直接失败。T108 §14 把此处描述为"ScopedName 取错侧"，
实测已推翻——代码从未走到 ScopedName。

```text
StChReqIf.Master mp_port → header = InterfacePortHeaderSyntax
                           header.nameOrKeyword = Token(StChReqIf)   ← interface 类型
                           header.modport       = DotMemberClause(.Master)
StChReqIf bare_port      → header = VariablePortHeaderSyntax
                           header.dataType      = NamedType(StChReqIf)
```

冻结做法：`InterfacePortHeaderSyntax` 用 typed token `header.nameOrKeyword` 绑定 interface 类型；
`header.modport` 的 `DotMemberClause` 内的名字 token 绑定对应 modport 记录；
保留既有 `VariablePortHeaderSyntax.dataType` 路径。非 ANSI 的 `if.modport x;` 体内声明形式
需取 ScopedName **左侧**——该分支真实存在，但属次要路径。

### 2.4 Struct —— 成员后接 select 时 `syntax` 是 `None`

现状：T108 §14 称"外层 typed syntax 是选择表达式"，实测为 `None`，没有 typed 结构可走。

```text
ar_fifo_rdat.ok        → MemberAccessExpression.syntax = ScopedNameSyntax   现在能work
ar_fifo_rdat.user[3:0] → MemberAccessExpression.syntax = None
                         sourceRange = [448:465]，正好是 "ar_fifo_rdat.user" 17 字节
```

冻结做法（**已被 §12 更正，见下**）：`MemberAccessExpression.syntax` 为 `None` 时，以 `sourceRange`
的**末端**锚定 `len(member_name)` 个字节，并用既有字节校验确认。校验失败则按既有规则保留，不猜。

### 2.5 安全性修正：interface 实例必须显式保留

层次引用前缀（`req2mshr_req_if.valid` 中的 `req2mshr_req_if`）目前**没有任何规则**：
`_semantic_expression_range` 走 ScopedName 只取右侧成员名。若 interface 实例被改名而前缀不改写，
gate 会残留旧名。

本任务不实现前缀规则，但必须把 `interface_instance` 与 `interface_instance_array`
**显式保留**，reason 为 `hierarchical_prefix_unsupported`。这是安全性修正而非能力回退：
在前缀规则落地前，改名这类对象本来就不安全。前缀规则归 T111。

## 3. 不包含的内容

- 不改变四个公开 category、`--encryption-rate`、mapping schema 2、SourceSet 语义、PySlang 编译配置；
- **不改动 `_apply_group_binding_issues` 的组级事务**——收缩爆炸半径归 T111，本任务保持隔离可复审；
- 不实现层次引用前缀、`NamedType` typedef 类型引用、`NamedParamAssignment`、
  `HierarchyInstantiation` 等其余类二规则；
- 不实现 T109 探测器的逐符号完整性判据；
- 不新增名称搜索、文本扫描、正则解析或第二套 owner 推断；
- 不运行 RISC-V-Vector Formal，不使用 blanket `unittest discover`。

## 4. 允许修改

- `rtl_obfuscator/rename_index.py`
- `tests/test_t110_binding_fixes.py`（新增）
- `tests/fixtures/t110_binding_fixes/**`（新增）
- `tests/test_t108_pyslang_rename_index.py`、`tests/test_t108_public_core_flow.py`
  （仅在既有断言因本次修复而改变时同步，不得放宽）
- 本任务单、`docs/development/architecture/token_first_binding.md`

## 5. 固定 fixture

新增 `tests/fixtures/t110_binding_fixes/design.f`，其 `design.sv` 必须同时包含：

- 命名端口连接顺序与端口声明顺序**不同**的实例化；
- `.*` 隐式连接与位置连接各一处；
- modport 限定的 ANSI interface port（`If.Mp p`）与无 modport 的 interface port；
- 非 ANSI 的 `if.modport x;` 体内声明；
- `struct_field[bit]` 与 `struct_field[part:select]`，以及嵌套同名成员 `data.a.a`；
- 一个被实例化多次的复用模块（验证目标身份不再按对象身份判歧义）；
- 一个 Yosys 可读的 Formal cone。

## 6. 机器可验收结果

`--category all` 在本地 fixture 上必须满足：

- 四组 `category_outcomes` 均 `rename > 0`；
- 服务器三个 signature 全部消失：不再出现
  `PortSymbol / semantic target has no unique physical typed token`、
  `DefinitionSymbol / ...`、`FieldSymbol / ...`；
- 端口连接标签的改名与其端口声明一致；重排顺序的实例化不产生错配；
- `interface_instance` / `interface_instance_array` 以
  `hierarchical_prefix_unsupported` 保留，且该 reason 不触发组级回滚；
- 被实例化多次的模块内符号不产生歧义，`mapping` range audit 无重复/重叠；
- `strict_compile_passed=true`、`restored_byte_identical=true`；
- actual renamed gate 的 Formal 正例 exit 0 且 `formal_equivalence=pass`；
  固定功能负例 strict compile 通过但 Formal 非零，含 `unproven` 或 `equiv_status -assert`。

## 7. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t110_binding_fixes tests.test_t108_pyslang_rename_index \
  tests.test_t108_public_core_flow tests.test_public_cli tests.test_mapping_vnext \
  tests.test_rewrite_vnext tests.test_orchestration_vnext tests.test_restore_vnext -v

conda run -n rtl_obfuscation python -m unittest tests.test_binding_coverage -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rename_index.py tests/test_t110_binding_fixes.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T110_core_group_binding_fixes.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t110_ready_for_review=pass")'
```

`tests.test_t110_binding_fixes` 必须实际调用 `scripts/formal_equivalence.py` 完成正负例，
并在输出或任务记录中给出 gold、actual gate、top、命令、退出码与 JSON。

## 8. 服务器验收（本任务的第二半）

```sh
export PROJ=/home/lufengchi/workspace/ChipPlatform
OUT=/home/lufengchi/workspace/test/stcache_all_t110_001

python rtl_encrypt.py \
  --filelist "$PROJ/aic_ss/src/stcache/StCache.f" \
  --top StChCore \
  --category all \
  --include-dir "$PROJ/common/src/StLib/common" \
  --include-dir "$PROJ/common/src/StLib/impl_template/tsmc4" \
  --output-dir "$OUT"
```

通过条件（对应用户的最低要求）：

- 无 `REFUSED_ATOMIC`；
- `strict_compile_passed` 与 `restored_byte_identical` 均为 `true`；
- **四组均 `rename > 0`**；
- preserve 原因只允许既有 `selected_top_boundary` / `outside_top_closure` /
  `macro_origin_conflict`，加上本任务新增的 `hierarchical_prefix_unsupported`；
  不得出现未解释的新原因；
- mapping schema 2，range audit 无重复、重叠或越界。

同时复跑一次 `scripts/binding_coverage.py`，确认 `byte_mismatch=0` 且
`join.in_scope_elaborated.ambiguous` 接近 0。

## 9. Formal verification

本任务产生改写 RTL，必须按 `docs/formal_verification.md` 在**本地 compact fixture** 上完成
一个 actual-gate 正例与一个固定功能负例。StCache 规模的 Formal 不属于本任务，
但第 8 节的 strict compile 与 byte-identical restore 是硬条件。

## 10. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 35a8e8a
starting_head_note: 合同第 5 行记录的 0e28030 是创建本任务时的 HEAD；本任务单与
  token_first_binding.md 的冻结提交 35a8e8a 之后才开始实现，实际 starting HEAD 为 35a8e8a
worktree_at_start: clean（`git status --porcelain` 无输出）
allowed_files_overlap_with_user_changes: none
tool_form: `conda run -n rtl_obfuscation` 在本沙箱报 `__conda_exe:6: permission denied`，
  改用同一环境的解释器 `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python`
first_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python -m unittest
  tests.test_t108_pyslang_rename_index tests.test_t108_public_core_flow tests.test_public_cli
  tests.test_mapping_vnext tests.test_rewrite_vnext tests.test_orchestration_vnext
  tests.test_restore_vnext  → Ran 27 tests, OK（baseline）
baseline_binding_coverage: tests.test_binding_coverage → Ran 15 tests, OK（baseline）
```

### 10.1 改动文件

```text
M  rtl_obfuscator/rename_index.py          §2.1–2.5 的 occurrence 绑定修复与目标身份统一
M  docs/tasks/T110_core_group_binding_fixes.md   本执行记录
A  tests/test_t110_binding_fixes.py        新增，14 个用例
A  tests/fixtures/t110_binding_fixes/design.f
A  tests/fixtures/t110_binding_fixes/design.sv
A  tests/fixtures/t110_binding_fixes/formal.f
A  tests/fixtures/t110_binding_fixes/formal_cone.sv
```

`docs/development/architecture/token_first_binding.md` 未改动（冻结提交 35a8e8a 已含本次口径）。

### 10.2 测试用例的两处缺陷与修正

两处缺陷都在 `tests/test_t110_binding_fixes.py`，与产品代码无关，`rtl_obfuscator/rename_index.py`
未因此改动一行。

1. **辅助方法名与 `unittest` 内部属性冲突（4 个 error）。**
   原辅助方法名为 `_outcome`。`unittest.TestCase` 在运行期把**实例属性** `_outcome` 绑定为
   runner 的 `_Outcome` 对象，实例属性优先于类方法，因此 `self._outcome(category)` 抛
   `TypeError: '_Outcome' object is not callable`。四个用例在断言执行前就 error，
   等于从未真正验证过。
   修正：重命名为 `_category_outcome`，同步 4 处调用点（现第 80、86、338、356 行），
   并在方法上留注释说明为何不得叫 `_outcome`。
   重命名后逐条核对断言与实测数值，全部相符，未放宽任何断言：
   `rename > 0` 且 `unsupported == 0`（四组实测 12/20/6/7，unsupported 全 0）；
   无 `source_binding_incomplete`；interface 组 `rename == len(eligible) == 6`、
   `preserve == len(instances) == 3`；四组 issues 不含
   `cross_record_range_conflict` / `macro_origin_conflict`。

2. **`test_wildcard_and_positional_connections_produce_no_label_occurrence` 选择范围写错（1 个 failure）。**
   断言 `len(wild_child_ports) == 3` 实得 16。经查是**测试的选择范围错**，不是产品缺陷：
   原选择用两个 module header 的 `rfind` 比较来界定 `t110_wild_child` 的字节范围，
   该写法只给出下界、没有上界，于是把 `t110_wild_child` 之后声明的所有端口一并收进来。
   `design.sv` 的模块顺序为 `t110_wild_child`(89–95)、`t110_wild_parent`(101–109)、
   `t110_top`(111–173)，三者端口合计正好 16 个，与实得数字一致。
   16 不是正确答案：`t110_wild_child` 只声明 `x, y, z` 三个端口，用例要证的正是
   `.*` 隐式连接不给**该子模块自己的端口**产生 label occurrence。
   修正：把范围收紧为该子模块自身的字节区间
   `wild_start = design.index(b"module t110_wild_child")` 到
   `wild_end = design.index(b"endmodule", wild_start)`（第 95 行的 `endmodule`，模块无嵌套）。
   同时把断言**加强**而非削弱——由数量断言改为按声明位置排序的精确名字断言
   `[symbol.name for symbol in wild_child_ports] == ["x", "y", "z"]`，
   再对每个端口断言 `semantic_port_connection` occurrence 为空、
   `support == "preserved"`、`reason == "outside_top_closure"`。

### 10.3 四组实测结果（公开 CLI）

```sh
/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python rtl_encrypt.py \
  --filelist tests/fixtures/t110_binding_fixes/design.f --top t110_top \
  --category all --output-dir <tmp>        # exit 0
```

```text
encryption_result=PASS_PARTIAL  strict_compile_passed=true  restored_byte_identical=true
rename=45 preserve=20 unsupported=0  modified_tokens=177  occurrence_coverage=1.0
mapping.schema_version=2

category_outcomes:
  signals    candidate=13 rename=12 preserve=1  unsupported=0  issues: outside_top_closure
  ports      candidate=36 rename=20 preserve=16 unsupported=0  issues: outside_top_closure,
                                                                       selected_top_boundary
  interface  candidate=9  rename=6  preserve=3  unsupported=0  issues: hierarchical_prefix_unsupported
  struct     candidate=7  rename=7  preserve=0  unsupported=0  issues: 无
```

四组均 `rename > 0`；无 `source_binding_incomplete`；服务器三个 signature
（`PortSymbol` / `DefinitionSymbol` / `FieldSymbol` + `semantic target has no unique
physical typed token`）均不再出现。

### 10.4 Formal verification

由 `tests.test_t110_binding_fixes.test_actual_gate_formal_positive_and_fixed_functional_negative`
实际调用 `scripts/formal_equivalence.py` 完成。gate 为**真实改名后的 actual gate**，
用例先断言 `gate/formal_cone.sv != fixture/formal_cone.sv`，不是恒等比较。
`yosys` 取自 PATH：`/opt/homebrew/bin/yosys`，`Yosys 0.53`。

正例：

```text
gold : tests/fixtures/t110_binding_fixes            （--gold-filelist formal.f --gold-root <fixture>）
gate : <tmp>/t110-formal-*/gate                     （--gate-filelist design.f --gate-root <gate>）
top  : t110_formal_top      seq: 5
cmd  : python scripts/formal_equivalence.py --gold-filelist <fixture>/formal.f \
         --gold-root <fixture> --gate-filelist <gate>/design.f --gate-root <gate> \
         --top t110_formal_top --seq 5
exit : 0
json : {"formal_equivalence": "pass", "gate": "<gate>", "gold": "<fixture>",
        "seq": 5, "top": "t110_formal_top"}
gate 侧 encrypt summary: strict_compile_passed=true rename=14 preserve=4
        unsupported=0 modified_tokens=49 restored_byte_identical=true
```

固定功能负例（在 actual gate 副本上改功能，非改名）：

```text
mutation : formal_cone.sv 内唯一的 `1'b0` → `1'b1`（t110_reorder）
strict compile : catalog parse/semantic = 0/0，top_overlay parse/semantic = 0/0（编译仍通过）
exit : 1（非零）
evidence : 输出含 `unproven` 与 `equiv_status -assert`
```

用时说明：该 fixture 的 Formal cone 极小（`stat` 报 12 cells / 43 wires），
裸跑 `yosys` 约 0.04s，因此整模块 14 个用例 0.5s 内跑完属正常，非跳过。

### 10.5 五条固定验收命令的实际结果

全部用 `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python` 代替
`conda run -n rtl_obfuscation python`（原因见 `tool_form`），按 §7 顺序执行，
逐条读 `OK` / `FAILED` 判决行本身，未用管道 `tail` 掩盖退出码。

```text
1  -m unittest tests.test_t110_binding_fixes tests.test_t108_pyslang_rename_index
     tests.test_t108_public_core_flow tests.test_public_cli tests.test_mapping_vnext
     tests.test_rewrite_vnext tests.test_orchestration_vnext tests.test_restore_vnext -v
   → Ran 41 tests, OK        exit 0
2  -m unittest tests.test_binding_coverage -v
   → Ran 15 tests, OK        exit 0
3  -m py_compile rtl_obfuscator/rename_index.py tests/test_t110_binding_fixes.py
   → 无输出                  exit 0
4  git diff --check HEAD
   → 无输出                  exit 0（本记录写入后复跑仍为 exit 0）
5  状态守卫 t110_ready_for_review
   → t110_ready_for_review=pass   exit 0
```

### 10.6 偏差与未覆盖边界

```text
deviation_product_code: none —— 未改动 rtl_obfuscator/rename_index.py，
  未触碰 _apply_group_binding_issues（§3 禁止），未放宽或删除任何断言、校验器与 fixture。
deviation_scope: 本次交付仅修 tests/test_t110_binding_fixes.py 的两处用例缺陷；
  两处均确认为测试缺陷，无一指向产品缺陷，故无需 Main Agent 裁决。
found_already_applied: 接手时磁盘上的 tests/test_t110_binding_fixes.py 已含这两处修正
  （疑为本任务先前一次未完成的执行留下）。本次未重复改写，而是逐条复核诊断与断言强度：
  确认 `_outcome` 调用点已全部消失、wildcard 范围已按子模块字节区间收紧且断言已加强，
  并用实测数值核对了 4 个曾被冲突吞掉的用例的每条断言。
uncovered_boundary_1: 非 ANSI `if.modport x;` 体内声明形式需取 ScopedName 左侧，
  fixture 的 t110_mp_nonansi 覆盖了该分支，但仍属次要路径，未做穷尽变体。
uncovered_boundary_2: 层次引用前缀未实现，interface_instance / interface_instance_array
  以 hierarchical_prefix_unsupported 显式保留（§2.5 安全性修正），前缀规则归 T111。
uncovered_boundary_3: ports 组的 preserve 中含 selected_top_boundary 与 outside_top_closure
  两类既有原因，本任务未收缩其范围；覆盖率提升归后续任务（§0）。
server_acceptance: §8 的 StCache 服务器验收未在本沙箱执行（无 ChipPlatform 源与服务器环境），
  属本任务"第二半"，需 Main Agent 在服务器上另跑。
risc_v_vector_formal: 未运行（CLAUDE.md 与 §3 均禁止在例行工作中运行）。
blanket_discover: 未使用 unittest discover。
git: 未 commit、未 push、未自设 ACCEPTED。
```

## 11. 主 Agent 独立本地验收记录

主 Agent 未采信子 Agent 自报结果，独立复跑第 7 节五条门禁并独立审查代码。

```text
reviewed_at: 2026-08-27
sub_agent_note: 实现由子 Agent 完成；其间两次因 API 鉴权 403 被外部终止，
  非自身逻辑错误，恢复后完成。子 Agent 模型与 T108 冻结的 GPT-5.6 Luna 不同——
  T110 合同未冻结模型，故不构成违约，此处显式记录不隐藏。

main_gate_1: exit 0；Ran 41 tests；OK（读 OK/FAILED 判决行，未经 tail 掩盖退出码）
main_gate_2: exit 0；tests.test_binding_coverage Ran 15 tests；OK
main_gate_3: exit 0；py_compile rename_index.py + test_t110_binding_fixes.py
main_gate_4: exit 0；git diff --check HEAD
main_gate_5: exit 0；t110_ready_for_review=pass

main_formal_positive: 真实 actual gate；exit 0；JSON formal_equivalence=pass；
  top=t110_formal_top；seq=5；gate=/var/.../t110-formal-cki6iuou/gate
main_formal_negative: exit 1；evidence "unproven; equiv_status -assert"；
  mutation 1'b0 -> 1'b1 in t110_reorder
main_formal_t108_regression: T108 正负例同样通过，无回归
formal_freshness: 本次 Formal 临时目录 cki6iuou 与上一轮 o71q2qqb 不同，确认真实重跑非缓存

main_cli_verification: 主 Agent 独立跑公开 CLI（--category all）：
  PASS_PARTIAL；strict_compile_passed=true；restored_byte_identical=true
  rename=45 preserve=20 unsupported=0；modified_tokens=177
  occurrence_coverage=1.0；symbol_coverage=1.0；plaintext_leakage_rate=0.0
main_category_outcomes:
  signals    candidate=13 rename=12 preserve=1  unsupported=0  reason outside_top_closure
  ports      candidate=36 rename=20 preserve=16 unsupported=0  reason outside_top_closure
  interface  candidate=9  rename=6  preserve=3  unsupported=0  reason hierarchical_prefix_unsupported
  struct     candidate=7  rename=7  preserve=0  unsupported=0
main_signature_check: 全程无 source_binding_incomplete；
  PortSymbol / DefinitionSymbol / FieldSymbol 三个服务器 signature 全部消失

main_code_review:
  - `_apply_group_binding_issues` 未出现在 diff 中，§3 边界守住
  - 四项修改的函数齐备：_record_id_for_declaration、_named_port_connection_syntax、
    _instance_ports_by_name、_interface_port_header、_interface_port_type_range、
    _interface_port_modport_token、_member_access_range
  - 无名称搜索、正则、文本扫描；无字节校验或 range 校验被移除
  - 唯一新增 `except Exception` 位于 _member_access_range，作用是把意外属性错误转成
    稳定 RENAME_INDEX_RANGE_INVALID，不是吞异常；该函数显式拒绝宏位置做偏移算术、
    拒绝跨 buffer、按 end.offset - len(name) 锚定并做字节校验，begin <= start.offset 时返回 None
  - wildcard 断言经复核为**加强**而非放宽：由 `len(...) == 3` 改为断言精确名字序列
    ["x","y","z"] + 每个端口的 semantic_port_connection 为空 + support/reason 逐项校验；
    原 bug 是 rfind 只限定下界，扫进了后续模块的 16 个端口
  - 主 Agent 自我更正：先前误把"任务单+产品文件合计 247 insertions"读作产品文件单独数字，
    据此怀疑产品被改动。产品文件前后均为 268 changed lines，实际未被改动，子 Agent 说法正确。

main_local_result: PASS
server_gate: PENDING —— §8 的 StCache 验收是本任务第二半，未通过前不得设 ACCEPTED
delivery_note: 为使服务器能 pull 到本次修复，主 Agent 在 server_gate 之前提交并推送。
  这是交付而非验收；沿用 T108 §11.1 的先例，并基于用户本轮给出的全权修改授权。

## 12. 服务器门禁退回与 §2.4 更正（主 Agent，2026-08-27）

服务器在提交 `09d36e0` 上运行第 8 节命令。结果：

```text
rename=5524  preserve=1560  unsupported=18  modified_tokens=19188
加密率 0.3704（12706 / 34307 行）
加密类型数 3：signals, ports, interface   ← struct 缺失
struct: candidate=541  rename=0  preserve=541  unsupported=0
struct issues 全部为：
  message=source_binding_incomplete  semantic_kind=FieldSymbol
  detail="semantic target has no unique physical typed token"
```

达成部分：`ports` 与 `interface` 由 0 变为真实改名，超过重构前 ports 单组 2636 的历史基线；
§2.2 端口标签配对、§2.3 interface port header、§2.1 目标身份三项验证有效；
`unsupported=18` 与历史 `macro_origin_conflict` 数量一致，属已知逐对象边界。

未达成：`struct` 仍 `rename=0`，§8 通过条件"四组均 rename > 0"不满足。

### 12.1 根因：§2.4 的触发条件被写窄了（主 Agent 的合同错误）

主 Agent 取服务器三个样本的源码上下文，发现全部是**sized cast 内的成员访问**：

```text
(CREDIT_W)'(comb_rd_data_pre.alloc_en)
(1)'(cl2waitc_cmd_if.chline_st)
(IID_W)'(ar_fifo_rdat.id)
```

本地精确复现后测得：

```text
ar_fifo_rdat.id            → MemberAccessExpression.syntax = ScopedNameSyntax           现在能 work
(IID_W)'(ar_fifo_rdat.id)  → MemberAccessExpression.syntax = ParenthesizedExpressionSyntax
                             sourceRange = [238:253]，覆盖 'ar_fifo_rdat.id'
                             末端锚定 end-len("id") = 'id'，字节校验通过
```

sized cast 内的 `syntax` **既不是 `None`，也不是 `_syntax_identifier_range` 能处理的种类**。
§2.4 把触发条件冻结为"`syntax` 为 `None` 时"，因此 `_member_access_range` 在真实工程里从未被调用。
末端锚定本身是正确的，被挡在门外的是那个前置条件。

这是主 Agent 的错误，不是子 Agent 的执行问题：子 Agent 严格实现了合同写的条件。
错误性质与 T108 §14 相同 —— **从单个本地样本推断形状，再把它写成冻结条件**。同类错误已连续两次。

### 12.2 更正后的冻结条件（取代 §2.4 的原措辞）

`MemberAccessExpression` 的 occurrence 解析改为两级，**不以 `syntax is None` 为前提**：

1. 先试既有 typed syntax 路径（`_syntax_identifier_range`）；
2. 该路径未给出结果时——无论原因是 `syntax` 为 `None`、为 `ParenthesizedExpressionSyntax`、
   还是任何其他未处理种类——退到 `sourceRange` 末端锚定 `len(member_name)` 字节 + 字节校验；
3. 既有守卫保持不变：宏位置不做偏移算术、跨 buffer 返回 `None`、
   `begin <= start.offset` 返回 `None`、字节不匹配返回 `None`。失败仍按既有规则保留，不猜。

同时新增回归 fixture：`struct_field` 出现在 sized cast `(W)'(s.field)` 内，
并保留既有的 `s.field[bit]` / `s.field[part:select]` / `data.a.a` 覆盖，证明四种形状走同一条路径。

### 12.3 边界不变

§3 的排除项全部维持：不动 `_apply_group_binding_issues`（爆炸半径仍归 T111）、
不实现层次引用前缀与 `NamedType`、不新增名称搜索或文本扫描。
本次退回不新建任务，在同一 T110 合同内修正后重跑第 7 节五条门禁与第 8 节服务器门禁。

## 13. §12.2 更正的执行记录（子 Agent，2026-08-27）

```text
status: READY_FOR_REVIEW
starting_head: 09d36e0（§11 delivery_note 的交付提交）
worktree_at_start: 仅 docs/tasks/T110_core_group_binding_fixes.md 被主 Agent 改动（§12 的退回记录）
tool_form: `conda run -n rtl_obfuscation` 仍报 `__conda_exe: permission denied`，
  全程改用同一环境的解释器 /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python
```

### 13.1 改动文件

```text
M  rtl_obfuscator/rename_index.py            仅 _member_access_range 一处：两级解析
M  tests/fixtures/t110_binding_fixes/design.sv  新增 sized cast 内的成员访问回归形状
M  tests/test_t110_binding_fixes.py          新增 2 个用例（14 → 16）
M  docs/tasks/T110_core_group_binding_fixes.md  本节 + 两处 status
```

`docs/development/architecture/token_first_binding.md` 未改动。

### 13.2 产品代码改动（唯一一处）

`_member_access_range` 由「`syntax` 非 `None` 就直接返回 typed 结果」改为两级解析，
**去掉 `syntax is None` 前置条件**：

```text
-    if syntax is not None:
-        return _syntax_identifier_range(catalog, syntax, expected)
+    typed = _syntax_identifier_range(catalog, syntax, expected)
+    if typed is not None:
+        return typed
```

即：先试既有 typed syntax 路径；该路径**未给出结果时**（`syntax` 为 `None`、为
`ParenthesizedExpressionSyntax`、或任何其他未处理种类）继续走既有的 `sourceRange` 末端锚定。
函数体其余部分一行未动，四道守卫原样保留：宏位置不做偏移算术、跨 buffer 返回 `None`、
`begin <= start.offset` 返回 `None`、字节校验不匹配返回 `None`。
`_syntax_identifier_range` 抛出的 `RENAME_INDEX_RANGE_INVALID` 仍原样上抛（不吞、不退化为猜测），
由既有 `_safe_occurrence_range` 转成组级 issue 并按既有规则保留。
docstring 同步更新为记录两种"typed 路径到不了成员 token"的形状。

未改动 `_apply_group_binding_issues`（§3 禁止）；未实现层次引用前缀、`NamedType`、
`NamedParamAssignment`、`HierarchyInstantiation`；未新增名称搜索、文本扫描或正则。

### 13.3 先在本地复现服务器故障，再修

fixture 新增两处 sized cast 内的成员访问（参数宽度与字面量宽度各一，对应 §12.1 的
`(CREDIT_W)'(...)` 与 `(1)'(...)` 两个样本），保留既有
`word.user[2]` / `word.user[7:4]` / `word.a.a` 覆盖：

```systemverilog
localparam int CAST_W = 2;
assign cast_o     = (CAST_W)'(word.ok);
assign cast_bit_o = (1)'(inner.a);
```

**改产品代码之前**，本地 fixture 复现出与服务器逐字一致的故障：

```text
struct  candidate=7  rename=0  preserve=7  unsupported=0
  message=source_binding_incomplete  semantic_kind=FieldSymbol  name=ok  start=2333
    detail="semantic target has no unique physical typed token"
  message=source_binding_incomplete  semantic_kind=FieldSymbol  name=a   start=2372
    detail="semantic target has no unique physical typed token"
（另有 7 条由组级事务连带产生的 source_binding_incomplete，覆盖该组其余对象）
```

start=2333 与 2372 正是两处 cast 内的成员 token。这证实 §12.1 的诊断：末端锚定本身没问题，
被挡在门外的是 `syntax is None` 前置条件。修复后同一 fixture 变为
`struct candidate=7 rename=7 preserve=0 unsupported=0`，issues 为空。

### 13.4 五种成员访问形状走同一条路径（实测）

```text
形状                              offset  owner                              provenance
word.user[2]        (bit select)    1806  struct/struct_field/user           semantic_member
word.user[7:4]      (part select)   1871  struct/struct_field/user           semantic_member
word.a.a            (nested outer)  1619  struct/struct_field/a (t110_word_t) semantic_member
(CAST_W)'(word.ok)  (sized cast)    2338  struct/struct_field/ok             semantic_member
(1)'(inner.a)       (sized cast)    2378  struct/struct_field/a (t110_inner_t) semantic_member
```

五处 owner 均 `support=eligible`、`reason=None`，字节内容与成员名逐字相符。
gate 侧实际改写已核对：

```text
assign GrwzirwBdasvY1gJtVTL = (CAST_W)'(Se3iwsVXkyk9Zae96YCQ.YiAN_VrMHLxlZXBMRojB);
assign kPOAJUdN9sdu8gqpgza9 = (1)'(We0b2kHI9QEHL7i07cra.xJAWA9spxj21mn8N7_k7);
```

`CAST_W` 是 localparam，不在四组范围内，按既有规则保持原文。

### 13.5 新增的 2 个用例

```text
test_all_member_access_shapes_bind_through_one_path
  断言上表五种形状全部以 semantic_member 命中成员 token 自身，owner 的
  category/kind/name/support/reason 逐项校验，并先用字节比较确认 offset 指向的确是该成员名。
test_sized_cast_members_do_not_regress_the_struct_group
  断言 struct 组 rename>0、rename==candidate、preserve==0、unsupported==0、issues==[]，
  且该组每个符号 support=eligible、reason=None——直接对住服务器
  candidate=541 rename=0 preserve=541 的失败形态。
```

未放宽、未删除任何既有断言、验证器或 fixture；既有 14 个用例一字未改（仅 §2.4 分节注释
补上 §12.2 引用）。

### 13.6 四组实测结果（公开 CLI，`--category all`）

```sh
/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python rtl_encrypt.py \
  --filelist tests/fixtures/t110_binding_fixes/design.f --top t110_top \
  --category all --output-dir <tmp>        # exit 0
```

```text
encryption_result=PASS_PARTIAL  strict_compile_passed=true  restored_byte_identical=true
rename=47 preserve=22 unsupported=0  modified_tokens=187
occurrence_coverage=1.0  symbol_coverage=1.0  plaintext_leakage_rate=0.0
mapping.schema_version=2   range_audit: declarations=69 occurrences=168 total_ranges=237

category_outcomes:
  signals    candidate=13 rename=12 preserve=1  unsupported=0  issues: outside_top_closure
  ports      candidate=40 rename=22 preserve=18 unsupported=0  issues: outside_top_closure,
                                                                       selected_top_boundary
  interface  candidate=9  rename=6  preserve=3  unsupported=0  issues: hierarchical_prefix_unsupported
  struct     candidate=7  rename=7  preserve=0  unsupported=0  issues: 无
```

四组均 `rename > 0`；全程无 `source_binding_incomplete`；残留 issue 中不含任何
`semantic_kind`（`PortSymbol` / `DefinitionSymbol` / `FieldSymbol` 三个服务器 signature 均不出现）；
preserve 原因只有 §8 允许的 `outside_top_closure` / `selected_top_boundary` /
`hierarchical_prefix_unsupported`。
与 §10.3 相比 ports 由 36→40 candidate、signals/interface 不变、struct 由 rename=0 恢复为 7，
ports 的增量来自 fixture 新增的 4 个端口（`cast_o` / `cast_bit_o` 及其在 `t110_top` 的对偶）。

### 13.7 Formal verification

仍由 `tests.test_t110_binding_fixes.test_actual_gate_formal_positive_and_fixed_functional_negative`
实际调用 `scripts/formal_equivalence.py`，gate 为真实改名后的 actual gate（用例先断言
`gate/formal_cone.sv != fixture/formal_cone.sv`）。`yosys` 取自 PATH。

```text
正例
gold : tests/fixtures/t110_binding_fixes  （--gold-filelist formal.f --gold-root <fixture>）
gate : /var/.../t110-formal-wszdmllb/gate （--gate-filelist design.f --gate-root <gate>）
top  : t110_formal_top     seq: 5
cmd  : python scripts/formal_equivalence.py --gold-filelist <fixture>/formal.f \
         --gold-root <fixture> --gate-filelist <gate>/design.f --gate-root <gate> \
         --top t110_formal_top --seq 5
exit : 0
json : {"formal_equivalence": "pass", "gate": "<gate>", "gold": "<fixture>",
        "seq": 5, "top": "t110_formal_top"}

固定功能负例（在 actual gate 副本上改功能，非改名）
mutation : formal_cone.sv 内唯一的 `1'b0` → `1'b1`（t110_reorder）
strict compile : catalog parse/semantic = 0/0，top_overlay parse/semantic = 0/0（编译仍通过）
exit : 1（非零）
evidence : 输出含 `unproven` 与 `equiv_status -assert`
```

formal_freshness: 本轮临时目录 `wszdmllb` 与 §11 记录的 `cki6iuou` 不同，确认真实重跑非缓存。
T108 正负例在同一次 gate 1 内一并通过（`T108_FORMAL_POSITIVE` exit 0 /
`T108_FORMAL_NEGATIVE` exit 1），无回归。
本次 fixture 改动只落在 `design.sv`，`formal.f` 只含 `formal_cone.sv`，故 Formal cone 未受影响。

### 13.8 五条固定验收命令的实际结果

按 §7 顺序执行，逐条读 `OK` / `FAILED (...)` 判决行本身并单独取退出码，
未用管道 `tail` 掩盖退出码（`conda run` 替换原因见 §13 的 `tool_form`）。

```text
1  -m unittest tests.test_t110_binding_fixes tests.test_t108_pyslang_rename_index
     tests.test_t108_public_core_flow tests.test_public_cli tests.test_mapping_vnext
     tests.test_rewrite_vnext tests.test_orchestration_vnext tests.test_restore_vnext -v
   → Ran 43 tests in 2.141s / OK        exit 0     （§10.5 为 41，本轮新增 2 个用例）
2  -m unittest tests.test_binding_coverage -v
   → Ran 15 tests in 0.180s / OK        exit 0
3  -m py_compile rtl_obfuscator/rename_index.py tests/test_t110_binding_fixes.py
   → 无输出                             exit 0
4  git diff --check HEAD
   → 无输出                             exit 0
     首跑曾报 `new blank line at EOF`（本节写入时多留一个空行），删除后复跑为 exit 0；
     该判决只涉及本任务单的文件尾空白，产品代码与用例未因此改动。
5  状态守卫 t110_ready_for_review
   → t110_ready_for_review=pass         exit 0
```

### 13.9 偏差与未覆盖边界

```text
deviation: none —— 本次改动完全落在 §4 允许修改的文件内，且严格等于 §12.2 冻结的两级解析。
  未触碰 _apply_group_binding_issues（§3），未实现 §3 排除的任何类二规则，
  未新增名称搜索/文本扫描/正则，未放宽或删除任何断言、校验器与 fixture。
behavior_change_note: 去掉前置条件后，typed 路径返回 None 的 ScopedNameSyntax 也会落到
  末端锚定。这不是放宽：末端锚定仍做字节校验，只可能返回字节等于成员名的区间，
  且 begin <= start.offset（无前缀）时拒绝。实测 word.a.a 两层成员各自锚定正确，
  内层 `a` 不被外层记录抢占（既有断言 test_struct_member_selects_... 继续通过）。
uncovered_boundary_1: 只覆盖了 sized cast 的两种宽度写法（参数与字面量）。
  其他"typed 路径到不了成员 token"的语法种类未穷举——但按设计它们全部落到同一条
  末端锚定 + 字节校验路径，失败则按既有规则逐个保留，不猜。
uncovered_boundary_2: cast 内再套 select（如 `(W)'(s.f[3:0])`）未加 fixture；
  该形状的 sourceRange 末端不是成员 token，字节校验会拒绝并逐个保留，属既有安全失败路径。
uncovered_boundary_3: §10.6 的三条边界不变（非 ANSI if.modport 次要路径、层次引用前缀归 T111、
  ports 组 selected_top_boundary / outside_top_closure 范围未收缩）。
server_acceptance: §8 的 StCache 服务器验收未在本沙箱执行（无 ChipPlatform 源与服务器环境），
  仍属本任务"第二半"，需主 Agent 在服务器上另跑。
risc_v_vector_formal: 未运行。 blanket_discover: 未使用。
git: 未 commit、未 push、未自设 ACCEPTED。
```

## 14. 主 Agent 对 §12.2 更正的独立本地验收

主 Agent 未采信子 Agent 自报结果，独立复跑第 7 节五条门禁并独立审查代码与产物。

```text
reviewed_at: 2026-08-27（§12.2 更正后）
main_gate_1: exit 0；Ran 43 tests；OK（读 OK/FAILED 判决行）
main_gate_2: exit 0；tests.test_binding_coverage Ran 15 tests；OK
main_gate_3: exit 0；py_compile
main_gate_4: exit 0；git diff --check HEAD
main_gate_5: exit 0；t110_ready_for_review=pass

main_formal_positive: exit 0；formal_equivalence=pass；top=t110_formal_top；seq=5
main_formal_negative: exit 1；evidence "unproven; equiv_status -assert"；mutation 1'b0 -> 1'b1
main_formal_t108_regression: T108 正负例同样通过，无回归
formal_freshness: 本轮临时目录 _xrqaw93，与子 Agent 的 2gb8ftlf 及 §11 的 cki6iuou 均不同，
  确认每次真实重跑；测试文件内无 skipTest/skipUnless/skipIf
formal_assertion_check: 测试内确有 assertEqual(positive_json["formal_equivalence"], "pass")，
  非仅打印证据

main_cli_verification（主 Agent 独立跑公开 CLI --category all）:
  PASS_PARTIAL；strict_compile_passed=true；restored_byte_identical=true
  rename=47 preserve=22 unsupported=0 modified_tokens=187
  signals    candidate=13 rename=12 preserve=1  unsupported=0
  ports      candidate=40 rename=22 preserve=18 unsupported=0
  interface  candidate=9  rename=6  preserve=3  unsupported=0
  struct     candidate=7  rename=7  preserve=0  unsupported=0
  程序化断言"四组均 rename>0 且无 source_binding_incomplete" = True
main_cast_rewrite_evidence: gate 内确认 sized cast 内的成员已被改写，例如
  (CAST_W)'(dhMhztiqd_apDXuuN0ez.cVWjLHY91RQuZ7_4EcU6) 与 (1)'(pFm8b64K7U4PyttTvT5G.ZeNYXToiapvOVFQDrzra)

main_code_review:
  - 改动仅一处：`_member_access_range` 去掉 `if syntax is not None: return ...` 的提前返回，
    改为先取 typed 结果、为 None 时继续走末端锚定。符合 §12.2。
  - 四道守卫全部在位：isMacroLoc 拒绝偏移算术、跨 buffer 返回 None、
    begin <= start.offset 返回 None、字节不匹配返回 None。
  - `_apply_group_binding_issues` 在 diff 中出现 0 次，§3 边界守住。
  - 未引入 re./regex/.find(/readlines 等禁止模式。
  - 子 Agent 自报的行为说明经复核成立：放开前置条件后，typed 路径返回 None 的 ScopedName
    也会走末端锚定，但锚定有字节校验且拒绝无前缀区间，不构成放宽。
  - 未覆盖边界（子 Agent 已记录，主 Agent 确认）：cast 内再嵌 select，如 (W)'(s.f[3:0])，
    其 range 末端不是成员 token，落到既有逐对象安全保留。

main_local_result: PASS
server_gate: PENDING_RETRY —— 服务器需拉取本次修正后重跑第 8 节命令
delivery_note: 为使服务器能 pull，主 Agent 在 server_gate 之前提交推送；这是交付而非验收。
