# T110：四核心组稳定改名的三处绑定修复与目标身份统一

- 状态：`READY`
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

冻结做法：`MemberAccessExpression.syntax` 为 `None` 时，以 `sourceRange` 的**末端**锚定
`len(member_name)` 个字节，并用既有字节校验确认。校验失败则按既有规则保留，不猜。

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
status: READY
starting_head: 0e28030
```
