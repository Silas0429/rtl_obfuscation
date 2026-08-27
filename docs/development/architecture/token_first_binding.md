# Token-first 绑定:方向倒置的论证与覆盖率测量

- 文档状态：`MEASUREMENT_READY_PENDING_SERVER_DATA`
- 记录日期：2026-08-27
- 起因：StCache（`ChipPlatform/aic_ss/src/stcache/StCache.f`，top `StChCore`）在提交 `c3cf87a` 上
  `ports/interface/struct` 三组 `rename=0`
- 本文只论证方向与测量方法，不授权修改产品；产品改造需另立任务合同
- 配套只读工具：[`scripts/binding_coverage.py`](../../../scripts/binding_coverage.py)
- 配套任务：[`docs/tasks/T109_binding_coverage_probe.md`](../../tasks/T109_binding_coverage_probe.md)

## 1. 问题不是形状太多，而是方向反了

当前 `rename_index.py` 从**语义符号**出发，对每种形状去取"它的物理 token 藏在哪个 typed 语法属性里"：
`header.dataType`、`syntax.decl.name`、`parent.type`、`zip(connections, portConnections)`……

这个方向天生不收敛，因为 **slang 的 AST 是为分析设计的，不是为改写设计的**，它会主动丢掉自己不需要的
语法链接。实测同一个语言概念（结构体成员引用）在 PySlang 11 中的两种表现：

```text
ar_fifo_rdat.ok        MemberAccessExpression.syntax = ScopedNameSyntax
ar_fifo_rdat.user[3:0] MemberAccessExpression.syntax = None
```

仅仅因为后面多了个 `[3:0]`，AST 就不再挂 syntax。工具在向 AST 索取它没有承诺提供的东西，
所以每种形状的答案都不同 → 每种形状一段兼容代码 → 尾巴无穷。

人类工程师的做法是相反方向：**枚举文本里的每个 token，再逐个判断它指向谁**（grep 出名字，逐个 hit 看）。
这个方向上完整性是可证的：hit 集合是封闭的，漏不掉。

## 2. 完整性可证与否，决定了爆炸半径

改名安全的本质是一个**关于文本**的命题：

> 改写这些 range 之后，不再残留任何指向该符号的旧名 token，且没有动到别的符号的 token。

语义优先的方向只知道"我找到了 12 个引用"，无法知道有没有第 13 个 —— **完整性不可证**。
项目于是用 [`_apply_group_binding_issues`](../../../rtl_obfuscator/rename_index.py) 的
"整个核心组一起 preserve"来代替证明。后果是：一个未知 token 干掉 3239 个 port。

倒过方向后，完整性变成一个逐符号的判据：

> 对旧名为 `n` 的符号 S：令 T = 源码集合中所有拼写 `n` 的物理 identifier token。
> 当且仅当 T 中不存在未归属 token 时改名 S；此时只改归属给 S 的 range，
> 完整性与不干扰性均可证。

这是个按名字建字典就能查的局部检查，买到的正是组级 preserve 想买的那份安全。
**未知形状的代价由"整组阵亡"变为"只影响恰好同名的那几个符号"** —— 从致命变为按比例。

组级事务并非全部要废除：struct typedef 与其字段是**一个不可分割的聚合**，
`_register_structs` 里按单个 aggregate 做的组保留是正确且必要的；共享物理 range 走
`_resolve_range_claims` 也正确。要收缩的只有"全设计同类别"这一层。

## 3. 两类 occurrence，只有一类曾是无穷的

| 类别 | 定义 | 数量级 | 处理方式 |
| --- | --- | --- | --- |
| 一、语义引用 | elaborator 已解析成符号的 token，AST 中有 `sourceRange` + 目标 | StCache 上 15219 个 occurrence 的绝大多数 | **一条通用规则** |
| 二、结构性 occurrence | 含义来自语法位置而非表达式绑定 | 有限、可从语法定义穷举 | 封闭的语法规则清单 |

**类一的通用规则**：每个 identifier token 归属于"包含它、且目标名等于 token 文本"的**最小区间**引用节点。

实测该规则对 `a.a.a`（变量与两层字段全部同名）给出三个不同符号，歧义 0；
对 `syntax = None` 的 `data.user[3:0]` 与保留 syntax 的 `data.a.a` 走**同一条路径**。

**类二**包含：声明名、`.port(...)` 连接标签、`#(.PARAM(...))` 命名覆盖、
interface port header 的类型与 `.modport` 限定、`end : label`、`'{field: v}` 模式键、
非 ANSI 端口列表、被实例化类型名、层次引用前缀。

回看 T069–T107 那 22 张打地鼠任务：module closing label（T076）、function closing label（T082）、
named function argument（T083）、struct pattern field key（T084）、parameter 默认值覆盖（T079）、
defparam（T071）—— **全部属于类二**。项目其实是在用一轮一次服务器往返的代价，
凭经验重新发现 SystemVerilog 的语法表。而真正无穷的是类一（表达式形态 × 上下文），
恰恰是被通用规则一次塌缩掉的那一半。

## 4. 一个必须承认的边界：声明维度里没有表达式

实测 `logic [ADDR_WIDTH-1:0] addr;`：

```text
DeclaredType.typeSyntax = IntegerTypeSyntax 'logic [ADDR_WIDTH-1:0]'
DeclaredType.type       = PackedArrayType 'logic[3:0]'
NamedValueExpression    = 无（slang 求值后丢弃了维度表达式）
```

维度里的 `ADDR_WIDTH` **不产生任何 AST 引用节点**，所以类一规则到不了它。要绑定只能用
`Lookup`/`LookupLocation` 在正确作用域里重解析（这是语言自身的作用域规则，不是名字猜测）。

但维度必须是常量表达式，只能引用 parameter、localparam、genvar、enum value ——
**全部在四个核心组之外**。因此这个洞不影响当前公开范畴，例外是
`$bits(some_struct_t)`、`type(sig)` 这类少见写法。本文如实记录该边界，不实现该遍历。

这也是为什么覆盖率必须**同时输出整体与 in-scope 两套数字**：整体分母含 parameter/genvar，
会把这个不影响决策的洞算进去；只有 in-scope 数字能预测四个核心组实际能改多少。

## 5. 探测器与它的判读

`scripts/binding_coverage.py` 是只读测量：两趟遍历（CST 全部 `TokenKind.Identifier` token；
AST 全部引用节点的 `sourceRange` + 目标）+ 类一通用规则 + 一趟声明归属，
残差按"最两层紧包含语法节点"做直方图。宏位置只经 `SourceManager.getFullyOriginalLoc` 还原，
每个 token 都做源码字节校验；不改写 RTL、不产生 gate、不引入任何 preserve/rename 决策。

### 5.1 目标身份必须是物理声明位置

首版探测器用 Python 对象身份 `id(target)` 标识语义目标，在 19 文件的
`rtl_samples/RISC-V-Vector` 上报出 1294 个 in-scope 歧义。根因是 elaboration：
`eb_one_slot.sv` 被实例化 4 次，同一物理声明产生 4 个不同 Python 对象，
于是同一个源码 token 被判为"4 个所有者竞争"。

改为按目标的**物理声明位置**标识后（与产品 `symbol_id` 的口径一致，
也是 `_record_for_semantic_target` 解决同一问题的方式）：

| 指标 | `id(target)` | 物理声明位置 |
| --- | --- | --- |
| in-scope 覆盖 | 70.75% | **92.47%** |
| in-scope 残差 | 1737 | **447** |
| in-scope 歧义 | 1294 | **0** |
| 可安全改名名字比 | 44.27% | **70.81%** |

这条经验对产品同样成立：**任何按 token 归属的实现都必须用物理声明范围而不是对象身份做目标标识。**

### 5.2 真实工程上的残差分布

`rtl_samples/RISC-V-Vector`（project-root，top `vector_top`，19 个 source unit，
7462 个物理 identifier token，`byte_mismatch=0`）的 in-scope 残差 447 个，全部落在四条规则族内：

| 残差 | token 数 | 占残差 | 性质 |
| --- | --- | --- | --- |
| `NamedPortConnection < HierarchicalInstance` | 388 | 87% | 端口连接标签 —— **服务器 ports 根因** |
| `NamedType < IdentifierName` / `< IdentifierSelectName` | 25 | 6% | 声明里的 typedef 类型引用 |
| `SimplePropertyExpr < SimpleSequenceExpr` | 16 | 4% | SVA 断言里的引用 |
| `IdentifierName < 各算术/比较表达式` | 18 | 4% | for 循环局部变量 `k`/`i` |

**单独实现 `NamedPortConnection` 一条规则，in-scope 覆盖即从 92.47% 升到约 99%。**
这是"封闭短尾"假设在真实工程上的直接证据。

小 fixture 上另外观察到的类二产生式（`InterfacePortHeader`、`DotMemberClause`、
`VariablePortHeader`、`HierarchyInstantiation`、`ImplicitNonAnsiPort`、
`IdentifierName < ScopedName` 层次前缀、`IdentifierName < CastExpression`、
`$no_enclosing_syntax`）合并后，本地已知产生式总数为个位数量级的十余条。

### 5.3 已知的口径不精确

- for 循环局部变量是 `VariableSymbol`，被本探测器计入 in-scope，而产品的 `signals` 只收
  `declaringDefinition` 为 module 的 Variable/Net。因此 in-scope 分母略偏大，
  覆盖率略偏悲观 —— 方向是安全的。
- `$no_enclosing_syntax` 表示语法节点的 range 跨了两个 buffer（宏体），
  探测器无法为其归类。这是**分类**能力的边界，不影响归属结果。

### 5.4 判读服务器数据的顺序

1. `tokens.byte_mismatch` 必须为 0。非 0 说明宏位置还原本身有问题，必须先修这一项，其余数字无意义。
2. `join.in_scope.ambiguous` 应接近 0。若很大，说明目标身份口径又退化成了对象身份（见 §5.1）。
3. `completeness.in_scope.renameable_name_ratio` —— 预测四个核心组能安全改名的比例，
   同时说明逐符号完整性判据能否替代组级爆炸半径。
4. `residual_in_scope_by_syntax_kind` 的产生式条数与头部集中度 —— 若头部一两条占绝大多数
   且与 §5.2 重合，"封闭尾巴"假设成立，可按频次排序进入产品改造。
5. `join.overall.coverage_ratio` 仅作参照，不用于决策。

## 6. 本文不主张的内容

- 不主张类一规则覆盖一切。第 4 节的维度边界是实测的反例。
- 不主张宏共享 token 可解：一个物理 token 被 N 次展开赋予 N 个语义，改名本身不可能同时正确，
  既有 `macro_origin_conflict` 逐对象策略保持不变。
- 不主张 strict compile 通过等于 gate 功能正确。SystemVerilog 在缺少 `default_nettype none` 时，
  端口连接里漏改的标识符会变成隐式 wire，**编译干净但功能错误**。因此真实工程的验收不能只有
  strict compile 与 byte-identical restore。
- 不授权任何产品改动。是否改造、以及改造顺序，由服务器测量结果决定。
