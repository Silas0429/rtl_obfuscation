# 未来扩展与已知边界

当前产品以 vNext 为唯一工作流：single-file、显式 filelist 和 `project-root + top` 共享
SourceSet、SourceCatalog、SymbolGraph、RewritePolicy、MappingVNext、actual gate、metrics 和
restore pipeline。19 个 canonical category 由一个 semantic owner registry 管理；默认选择为
前 13 类，module/type/interface ABI 必须显式 opt-in。

本文件只记录当前交付范围之外的事项。使用方法和当前入口见根目录
[`README.md`](../README.md)。

## 语言语义边界

- T071 已将物理可定位的 module type parameter 与语义绑定的 `defparam` 转为 module-owner
  safe-preserve：type parameter 本身和其 owner 全部保持，`defparam` 引用/目标 owner 全部保持；
  无法证明物理 declaration、typed binding token 或 owner 时仍保持 fail-closed。package/class
  scope、其他 type parameter、DPI、bind、checker、primitive、clocking block 和 virtual interface
  仍需要额外的 PySlang owner 证据。
- T069 已补齐真实工程 CDC FIFO 和 riscv-dbg JTAG wrapper 中复现的 value parameter
  sized-cast occurrence 边界：`WIDTH'(0)`、`POINTER_WIDTH'(~0)`、`IrLength'(4'b0101)`
  等 cast type token 现在通过精确 parameter declaration identity 绑定，并进入同一
  mapping/edit。T069 compact actual gate 已验证 strict compile、逐字节恢复及 Formal
  正负例；后续真实工程复测仍应保留这些闭包作为独立边界证据。
- T070 已按 PySlang typed syntax kind 忽略 `SignedCastExpressionSyntax` 内建 keyword cast
  及其 `TypeAliasType` 隐式 wrapper；typedef identifier cast 仍精确绑定，无法证明 direct
  type token 的普通 `TypeAliasType` conversion 继续 fail-closed。
- T072 已将能够由 semantic declaring definition 唯一证明 physical module owner 与
  source-backed module syntax span 的 nested generate 转为 module-span safe-preserve；该 span
  内全部 source symbols（包括 generate block scope）保持不改名，无法证明 owner/span 的形状
  仍保持 fail-closed。nested generate 内部 genvar/层次对象改名、instance array、conditional
  generate、复杂层次路径和完整 import/export member 语义仍需要专项 semantic coverage。
- T073 已将已有普通物理 `ModuleOwner` 内可由 `isMacroLoc()` 与
  `getFullyExpandedLoc()` 唯一映射到 module span 的宏 declaration/reference/register/assert
  来源转为 owner safe-preserve；宏生成 range 不进入 graph，已物理收集 symbol 统一使用
  `owner_contains_macro_source`，宏 module-type 的 semantic target owner 也原子保护。无法证明
  普通物理 owner、semantic target 或精确 span 时仍 fail-closed；宏生成 module definition name、
  宏文本展开/改写、include/条件编译和 macro argument rename 仍不支持。
- 顶层 interface/modport ABI 必须保持 top boundary；只有 closure 内且完整绑定的内部 ABI 才能
  显式改写。

## T073 后真实工程复测边界

本轮真实工程复测没有错误 gate 被发布：不完整或无法证明安全的改写均在 mapping、strict
compile 或 owner/build-input 检查阶段原子停止。但是，“安全拒绝或少加密”不等于“支持成功”；
strict compile 只能排除语法和绑定错误，不得代替可运行时的 actual-gate Formal。

- T075 已增加 **owner occurrence firewall**：受保护 owner 内不得产生跨 owner rename edit；
  `register_interface` 暴露的半改名风险现在会将整条跨 owner symbol 标为 unsupported，并禁止其
  产生任何 rewrite edit。
- T076 已支持普通物理 module 的直接 closing label `endmodule : name`，使子 module declaration、
  实例化引用和 closing label 使用同一个 rename record；selected top 的名称与 label 保留。
  direct identifier sized-cast 已支持；T080 进一步只支持 exact typed path
  `$clog2(<direct IdentifierName>)'(...)`，通过 lexical scope 绑定已有 module value/local parameter
  record，并记录 `expression_sized_cast_type`。其他 expression-sized cast 以及 enum/base dimension
  仍可能漏收集，保持 fail-closed。
- T079 已支持被 instance override 替换 semantic value 的 module value/local parameter 默认
  initializer direct identifier：只遍历精确 `DeclaratorSyntax.initializer` typed subtree，并用
  declaration `parentScope.lookupName()` 绑定到已有 parameter record。v1.1 仅凭 direct parent、
  `parent.key` 及 token buffer/offset/rawText identity 排除 structured assignment-pattern member key；
  value-side identifier 仍走精确 parameter binding，这不代表支持 `struct_fields` 改名。type/package/class
  parameter、macro default、hierarchical/scoped name 和普通 syntax text recovery 仍不支持；同一物理
  range 若绑定到不同 parameter target 则继续原子失败。
- **package-qualified enum/member** 的右侧物理范围仍可能无法和 semantic target 对齐，无法证明
  精确绑定时继续原子失败。
- T081 已为 `enum_values` 增加 record 级词法覆盖完整性防火墙：只有 declaration 与已有 semantic
  occurrences 的 ranges 和全部物理输入中的同名 plain identifier ranges 精确相等时才允许改名；
  覆盖不完整的单条 record 使用 `enum_lexical_coverage_incomplete` 原子禁用全部 edit。raw inventory
  故意包含 comments、strings、宏与 disabled text，可能保守减少加密，但不会据此猜测语义 target 或
  补 lexical occurrence；generic enum reference recovery 仍不支持。
- T082 已支持普通物理 function 的直接 closing label `endfunction : name`：只从同一 semantic
  `SubroutineSymbol` 的 exact `FunctionDeclarationSyntax.endBlockName.name` 取得非 missing 物理 token，
  并以 `semantic_function_end_label` 加入既有 `functions` record；没有 label 不新增 occurrence，名称、
  range 或 record ownership 证据不完整时继续 fail-closed。task、method、class/interface/package/program/
  checker/generate closing label、宏生成 label、extern/DPI/prototype 和 source-text recovery 仍不支持；
  Yosys 当前无法读取合法的 function closing-label 语法，因此该 label 的字节正确性由 PySlang strict、
  同 symbol edit 与 source-free restore 证明，Formal 只覆盖不启用 label 宏的 actual renamed gate。
- T077 已将原 **conflicting quarantine reasons** 边界收敛；T077 已对同一 ordinary owner
  的多个现有 quarantine reason 使用 `owner_contains_multiple_unsupported_constructs` 原子保护；
  owner/span 证据不一致和未知 reason 仍 fail-closed。
- **syntax-less implicit typedef conversion** 没有可证明的直接源码 token 时继续 fail-closed。
- VeeR 的宏 module definition name、SCR1 的 header/package 宏位置、Ibex 缺外部 primitive，
  分别属于当前 ModuleOwner 表达边界、owner 边界和 build-input 边界。

本小节只记录已观察边界，不授权实现或放宽现有 fail-closed 条件。

## 工程输入与验证

- T078 已将 persisted `compile_order`（独立编译单元）与 `included_files`（参与 manifest、hash
  和逐字节恢复的 header）分开审计，公开 direct restore 可恢复这两类物理文件；pinned Ibex 的
  `abi_group` 与 `non_abi_group` 仍是独立 strict-compile 边界，不属于该修复。
- 更复杂的 include/define 条件、嵌套 filelist、library/blackbox 和外部消费者需要扩展
  SourceSet/SourceCatalog 合同。
- 每项扩展都必须保留 semantic owner、physical range、strict compile、restore byte identity、
  coverage/leakage 和 Yosys 正负例证据。
- RISC-V-Vector 专项仍属于专门发布边界；普通产品任务不启动该场景驱动，通用 Formal view/alignment
  只通过 vNext API 复用。

## 后续方向

- 为复杂 SystemVerilog scope 建立更多 semantic object 到 source range 的精确映射；
- 为顶层 interface ABI 增加非 vacuous 的 formal 证明边界；
- 为外部 IP/blackbox 提供显式、可审计的 owner 和 preserve contract；
- 在不改变当前 report/schema/rate/metrics 方程的前提下，扩展 testbench、约束和软件模型消费者。
