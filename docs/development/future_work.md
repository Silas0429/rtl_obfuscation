# 后续工作

本文只记录当前 T108 之后尚未承诺的方向，不授权在现有任务中实现。

## 当前不属于四核心组的对象

module 名称、parameter、enum、function/task、argument、genvar、class、package 和其他旧细分类不属于当前
公共 `--category` 接口。需要重新立项并定义 PySlang semantic target、物理 range、strict compile、restore
和 Formal 边界；不保留旧分类兼容层。

## 可能的后续扩展

- 更完整的 interface instance array member/connection 语义覆盖；
- 外部 IP、blackbox 和顶层 ABI 的显式 preserve contract；
- 与仿真、综合和约束文件消费者配套的 gate 检查；
- 更大工程的性能测量，但不得重新引入第二套 owner/scope 推断；
- 对 Yosys 不支持的 interface/aggregate 语法补充 PySlang strict、range、restore 和其他等价性证据。

任何新语法形状必须先冻结独立任务合同。compile/elaborate 通过本身不能替代物理绑定证明，也不能授权
通过名称搜索、正则解析或 canonical type shape 猜测 owner。
