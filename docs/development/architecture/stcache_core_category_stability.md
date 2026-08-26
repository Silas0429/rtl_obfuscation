# StCache 四组核心类别能力边界与稳定化方案

- 文档状态：`T105_LOCAL_ACCEPTED / T106_LOCAL_ACCEPTED / INTERFACE_RESEARCHED`
- 记录日期：2026-08-26
- 研究基线：`fb2fa29 [FIX] Add symbol-level macro provenance protection`
- 外部输入：`ChipPlatform/aic_ss/src/stcache/StCache.f`，top `StChCore`
- 范围：`signals`、`ports`、`interface`、`struct/union`

本文记录服务器 StCache filelist 的真实运行结果，以及 interface 和 struct/union 从当前
fail-closed 边界收敛到稳定加密所需的实现设计。本文是开发者事实与后续任务输入，不替代
[`README.md`](../../../README.md) 的用户操作说明。

## 1. “支持”判定

必须区分三层证据：

1. compact fixture 中存在 declaration/reference 和真实 rename，只证明该语法形状已有实现；
2. `PASS_FULL` 或 `PASS_PARTIAL`、strict compile 和 byte-identical restore，只证明当前输入能够安全生成 gate；
3. actual renamed-gate Formal 正例和固定功能负例，才补充证明合同覆盖范围内的功能等价性。

`REFUSED_ATOMIC` 证明工具没有发布无法审计的半成品，不等于该类别加密成功。StCache 当前尚未运行
actual-gate Formal，因此下表中的工程结论只到 strict compile 与 restore 层。

## 2. 当前能力矩阵

| 类别 | StCache 结果 | 已证明能力 | 当前边界 |
| --- | --- | --- | --- |
| `signals` | `PASS_FULL`；rename 3183，preserve 0，unsupported 0 | 当前 filelist 内全部 selected signal 完成改名；strict compile 与 byte-identical restore 通过 | 尚无 StCache actual-gate Formal |
| `ports` | `PASS_PARTIAL`；rename 2636，preserve 587，unsupported 18 | 2636 个端口一致改名；strict compile 与 restore 通过 | 422 个 `outside_top_closure`、165 个 `selected_top_boundary` 为既有策略；18 个 `macro_origin_conflict` 暂不修改 |
| `interfaces` | graph 单项 5 个 eligible | interface 类型 declaration/reference 的 compact 与 StCache graph 路径可建立 | 完整 `interface` 因 interface instance array 原子拒绝 |
| `interface_instances` | `REFUSED_ATOMIC` | 普通标量实例和 compact 宏来源已有改名证据 | PySlang `InstanceArraySymbol` 下的 element `InstanceSymbol` 名称为空；当前 collector 错把 element 当物理声明 |
| `interface_ports` | StCache 单项 `REFUSED_ATOMIC` | 普通 interface 成员、modport member occurrence 和 compact port 已有证据 | 单独选择时仍强制读取未选择的 modport record，违反 selected-category 隔离 |
| `modports` | graph 单项 10 个 eligible | modport declaration/reference 可建立 | 尚未独立生成 StCache gate；完整 interface 先被实例数组阻断 |
| `struct_types` / `struct_fields` | 最近一次 StCache 为 `REFUSED_ATOMIC` | T105 compact 中类型、字段、隐式 conversion、direct cast、strict/restore 和 actual-gate Formal 已验收 | 通用修复已完成；StCache 仍需用新输出目录重跑，不能沿用旧失败结果推断工程结论 |
| `union_fields` | StCache 未单独测试 | compact union 字段及宏来源已有改名证据 | `--category struct` 不包含 `union_fields`；完整 StCache union 能力尚无外部证据 |

ports 的 18 个 unsupported 来自两个物理宏 token：`ASSERT_DEFAULT_CLK` 正文中的 `clk` 和
`ASSERT_DEFAULT_RST` 正文中的 `rst_n`。它们分别被多个 module port 绑定，一个物理 token 不能同时写入
多个随机密文名。该问题保持现状，不属于本方案的 interface/struct 实现范围。

## 3. 共同根因

PySlang semantic tree 同时包含：

- source-backed declaration/reference：源码中存在唯一可验证的 identifier token；
- elaboration alias/wrapper：例如 interface instance array 的每个 element；
- implicit semantic conversion：编译器为赋值或连接插入，但源码没有显式类型名；
- system/compiler metadata：例如 `SystemCallInfo`。

当前 `_collect_extended_symbols()` 在部分路径中把“存在 semantic object”近似为“必须存在 source
identifier”。这会让合法且已通过 compile/elaborate 的代码在 mapping 前失败。稳定实现必须冻结下面的
唯一规则：

```text
只有 source-backed selected declaration 建立一个 rename record；
只有源码中真实出现且语义绑定到该 record 的 identifier 建立 occurrence；
elaboration wrapper、implicit conversion 和 compiler metadata 只提供绑定证据，永远不伪造 range。
```

不能用名称白名单、源码文本搜索、吞异常、whole-owner preserve 或第二套 collector 规避该规则。

## 4. Interface 稳定化设计

### 4.1 Instance array 归一化

PySlang 11.x 对：

```systemverilog
bus_if array_if[3:0](.clk(clk));
```

提供一个 source-backed `InstanceArraySymbol(name="array_if")`，并为四个 elaborated element 提供
`InstanceSymbol(name="", arrayPath=[...])`。正确映射是：

1. 只为 `InstanceArraySymbol` 建立一个 `interface_instances` record；
2. declaration 使用 `InstanceArraySymbol.location` 和 `name`，必须精确匹配物理 `array_if` token；
3. 所有 element `InstanceSymbol` 只注册为该 record 的 semantic alias，不建立 declaration/edit；
4. `array_if[index]`、member access、module/interface connection 中的物理 base token 都归入同一 record；
5. 标量 `InstanceSymbol` 仅在名称非空、`arrayPath` 为空且 declaration 可物理定位时建立 record；
6. top 内直接声明的 interface instance 继续遵守 `selected_top_boundary`，不得因数组支持绕过 ABI 保护。

这套归一化应基于 `InstanceArraySymbol` / `elements` / `arrayPath` 的 PySlang 类型事实，不按实例名、文件或
工程路径特判。

### 4.2 Semantic target registry

当前 `record_for_target()` 会尝试对任意对象执行 `_record_range()`，因此 interface-only graph 也会探测
无源码的 `SystemCallInfo`。后续实现应收敛为两个索引：

```text
semantic object identity -> existing source-backed record
physical declaration range -> existing source-backed record
```

`add_target()` 只注册已建立 record 的 declaration object、合法 wrapper 和 array elements。
`record_for_target()` 先查 semantic identity；只有已授权的 source declaration 类型才能尝试 physical
range lookup。未知 metadata 直接返回“不是 selected source target”，不得制造错误或 fallback range。

### 4.3 Category 隔离

`interface_ports` 和 `modports` 是两个独立 category：

- modport 内的 `input data` / `output valid` 是 interface member occurrence，可在只选择
  `interface_ports` 时绑定；
- module header 中 `bus_if.consumer bus` 的 `consumer` 是 `modports` occurrence，只在选择
  `modports` 时记录；
- 只选择 `interface_ports` 时，不得因为不存在 unselected `modports` record 而报 owner mismatch；
- 快捷值 `interface` 同时选择四类，仍应建立完整交叉引用。

### 4.4 Interface 验收边界

后续实现任务至少覆盖：

1. scalar interface instance 和一维/多维 instance array；
2. 数组 element 的 indexed member access、named connection 和 interface port 连接；
3. `interfaces`、`interface_instances`、`interface_ports`、`modports` 四个单项及快捷值 `interface`；
4. array 只产生一个 source declaration record，element 不产生空名 record；
5. top boundary、outside closure、macro provenance 和 range 去重保持不变；
6. public gate strict compile、manifest/range audit、direct restore；
7. compact actual renamed-gate Formal 正例与固定功能负例；Yosys 无法直接承载的 interface 语法必须由
   PySlang strict、精确 edit/range 和 source-free restore 补充，不能把无 interface 的 Formal 当成完整
   interface 语义证明；
8. StCache `--category interface` 不再 `REFUSED_ATOMIC`，并报告真实 rename/preserve/unsupported。

## 5. Struct/union 稳定化设计

### 5.1 显式 cast 与隐式 conversion 分离

PySlang 11.x 的最小事实：

```systemverilog
value = pair_t'(rhs);  // ConversionExpression.syntax == CastExpressionSyntax
value = {a, b};        // implicit ConversionExpression.syntax == None
```

第二种 conversion 的结果类型可以是 `TypeAliasType(pair_t)`，但源码中没有 `pair_t` token。正确处理是：

1. `syntax is None`：编译器插入的隐式 conversion，不是 source occurrence，直接跳过；
2. `CastExpressionSyntax`：显式 cast，只接受语义 alias 与物理 type token 精确一致的引用；
3. built-in `signed'(...)` / `unsigned'(...)` 继续不是 typedef/struct occurrence；
4. 显式 cast 存在但无法映射 direct/scoped exact token 时继续 fail-closed，不使用文本恢复；
5. 跳过隐式 conversion 不会漏改源码，因为该节点本来没有 alias 拼写；alias declaration 和其他物理引用
   改名后，gate 重编译会重新生成相同隐式类型转换。

T105 已在本地 compact filelist 中落实并验收这条边界：`struct_types`、`struct_fields` 和
`union_fields` 均产生真实 rename，strict compile、byte-identical restore 以及 actual renamed-gate Formal
正负例通过；Formal 正例直接比较公开生成的 `formal.sv` gate，且证明锥包含真实改名的 aggregate type/field。
这不是 StCache 外部工程的完成声明，外部 filelist 仍需单独重跑。

### 5.2 T105 本地验收与外部边界

T105 本地验收已经覆盖：

1. packed struct/union 类型和字段 declaration/member reference；
2. concatenation、literal、assignment、port connection 产生的 syntax-less implicit conversion；
3. direct typedef/struct cast 的 type token 一致改写；
4. direct named struct assignment-pattern key 的既有闭包不回退；
5. macro argument/body provenance 和冲突保护继续按 selected symbol 处理；
6. `struct_types`、`struct_fields`、`union_fields` 单项以及 `struct + union_fields` 组合；
7. strict gate、range/manifest audit、byte-identical restore、actual renamed-gate Formal 正负例；

第 8 项仍是外部验收：StCache struct/union 分项与组合运行应不再因无源码 implicit conversion 原子拒绝。

T106 本地已验收，并在 compact filelist 中进一步验证了同名 aggregate alias 的 semantic-target 绑定：每个
`TypeAliasType` 先按 semantic declaration range 落到唯一 physical alias record，再校验源码 token
字节；aggregate member 通过语义 `FieldSymbol` 的 declaration range 绑定，不再按名称选择 owner。显式
cast、member named type、function return、selected/unselected port type 和 variable/net declared type
均有逐 occurrence 的 declaration/range/source-byte 证据；ports-only 不进入 aggregate resolver。T106
compact gate 为 `PASS_FULL`，strict compile、range/manifest audit、byte-identical restore、actual
renamed-gate Formal 正负例均通过。StCache 外部 struct/union 仍需服务器使用新输出目录重跑，不能用
compact 结果替代工程证据。

union/array/default/type/literal/macro/anonymous pattern key 等既有未授权形状不随本修复自动扩张；它们需要
各自的 exact semantic owner 和 physical token 证据。

## 6. 后续实现顺序

为保持任务小而可验收，实施只分两步，不再继续按具体工程名称、类型名或语句逐项补丁：

1. struct/union：T105 已完成 source-occurrence 修复、compact 与 Formal 本地验收；StCache 外部重跑待用户执行；
2. interface：再引入 source-backed `InstanceArraySymbol` record、element semantic alias 和独立 category
   依赖，并完成 compact、Formal 和 StCache 验收。

两步完成后，使用新的输出目录分别运行四组 category，再运行
`signals + ports + interface + struct + union_fields` 组合 gate。ports 的共享宏冲突仍按现状报告，不得把
组合结果中的这 18 个 unsupported 误归因于 interface/struct。

## 7. 完成标准

interface 和 struct/union 只有同时满足以下条件才能从“compact capability”提升为“StCache 工程可用”：

- selected graph 不因 elaboration-only/implicit semantic nodes 原子拒绝；
- mapping 中不存在空名称、伪造 range 或未选 category record；
- 每个实际改名对象的 declaration 与 occurrences 都精确对应输入字节；
- strict compile、manifest/range audit 和 byte-identical restore 全部通过；
- `rename / preserve / unsupported` 可解释，preserve/unsupported 只来自明确合同边界；
- compact actual renamed-gate Formal 正例和固定功能负例通过；
- StCache 外部重跑证据已记录，不能只用小型 fixture 推断真实工程支持。
