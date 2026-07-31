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
- instance array、嵌套或 conditional generate、复杂层次路径和完整 import/export member 语义
  仍需要专项 semantic coverage。
- 顶层 interface/modport ABI 必须保持 top boundary；只有 closure 内且完整绑定的内部 ABI 才能
  显式改写。

## 工程输入与验证

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
