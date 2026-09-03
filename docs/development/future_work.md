# 后续工作

本文只记录当前 T108 之后尚未承诺的方向，不授权在现有任务中实现。

## 当前 include 物理闭合边界

任意文件后缀不会因此成为 standalone suffix。只有已列 source/header/context 通过当前目录或 `+incdir+` 的
字面量 include 直接或递归唯一解析到的普通文件，才会作为只读 include-only physical dependency；同一路径去重，
并保留到 manifest、gate 和 restore。宏或其他预处理计算出的 include 不自动登记；若 PySlang parse 打开未登记的
真实 source/include buffer，工具会在 SourceCatalog 全树遍历或 FAST 改名索引开始前带路径拒绝。该边界不包含宏 include 自动发现、glob、
absolute include、`-y`、`+libext+` 或 library map。

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

## 供应商库的当前边界

当前产品不是完整 vendor parser 或 simulator compatibility layer。T121 只对 PySlang 11.0.0 中已用真实输入定位的
`IfNoneEdgeSensitive` 以及 `protect`、`endprotect`、`suppress_faults`、`enable_portfaults`、
`disable_portfaults`、`nosuppress_faults` 做精确分类。只有诊断能回到普通物理文件的预期 token/整行字节，且
`protect/endprotect` 不嵌套、一一配对时才继续。这些文件仍参与 compilation/elaboration，但整文件只读。

这一有限放行**不包括**：

- 真正加密、不可见的 protect payload；
- UDP、专有 primitive、新 simulator directive 或其他尚未证明可恢复的诊断；
- SDF、Liberty、testbench、VPI/PLI、fault simulation 配置和外部层次路径的同步改写；
- 跳过 top 所需 module definition，或自动生成 blackbox/module-interface stub。

新诊断默认仍 fail closed；不能只按诊断码整体忽略，也不能按目录名、文件名、module 名或文件大小猜测供应商归属。

## Library role 和只读策略的后续设计

`-v PATH` 当前仍与裸 `PATH` 完全同义，canonical gate `design.f` 只保留普通 compile order，mapping schema
也不持久化 library metadata。当前不实现真实 `-v` lazy library search、`-y`、`+libext+`、library map、
PVT corner 优先级或 duplicate definition 选择。

`--rewrite-root` 只是用户所有权/改写权白名单：目录放得过大会授权更多文件，放得过小会降低改名覆盖率，但目录外文件仍会编译且不改写。没有特殊诊断、却被放入 rewrite root 的第三方代码仍可能被改写；工具不从版权头自动判断。

将来的完整方案应另立任务同时定义：

1. 可持久、可审计的 library role 和显式 readonly 清单；
2. 与仿真器一致的惰性 resolution、搜索顺序、PVT/duplicate 选择；
3. 无法解析模型的 blackbox/stub 接口提取与参数/条件宏边界；
4. 使用抽象模型后的 proof scope 和服务器仿真、timing、SDF/fault 验收证据。

不应在当前诊断白名单上逐条堆叠成第二套 parser。T121 的 compact Yosys Formal 仅是仓库内改写验收，不证明真实 timing/SDF/fault 模型可由 Yosys 处理；服务器后续应用实际 simulator 另行验证 compile/elaboration 和必要的 timing/fault 流程。

## 混合 filelist 的发布审计

服务器下一轮测试不能只看命令退出码。需从 `mapping_execution.per_file_mapping` 确认：

- 所有 landed `rename` range 均位于指定 rewrite roots；
- `readonly_vendor_model` 和 `outside_rewrite_root` 文件没有 landed edit，且 input/gate hash 相同；
- include-only 物理文件（可为任意后缀）存在于 gate 和 manifest、未进入 `design.f`、hash 不变；
- direct restore 对所有物理输入逐字节一致，实际 simulator 能完成所需 compile/elaboration。

任何新语法形状必须先冻结独立任务合同。compile/elaborate 通过本身不能替代物理绑定证明，也不能授权
通过名称搜索、正则解析或 canonical type shape 猜测 owner。
