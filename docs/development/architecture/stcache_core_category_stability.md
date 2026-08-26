# StCache 四组核心类别状态

- 文档状态：`T108_LOCAL_REPLACEMENT_READY_PENDING_SERVER_GATE`
- 记录日期：2026-08-26
- 外部输入：`ChipPlatform/aic_ss/src/stcache/StCache.f`，top `StChCore`
- 公共范围：`signals`、`ports`、`interface`、`struct`

本文区分 compact/local 证据和服务器 StCache 证据，不把前者推断成后者。

## 当前实现规则

PySlang compile/elaboration 是唯一语义权威。只有 source-backed semantic declaration 建立 record；只有
直接 semantic target 且能映射到唯一物理 identifier token 的引用建立 occurrence。

- `signals`：module-owned `VariableSymbol/NetSymbol`，排除端口、parameter、interface/aggregate 成员；
- `ports`：source-backed module `PortSymbol`，selected top 的外部 ABI 按边界保留；
- `interface`：interface 类型、实例 root、成员、modport；`ModportPortSymbol` 是已有 member 的 alias/
  occurrence，数组 element 只作 alias，不产生空名 record；
- `struct`：物理 `typedef struct/union` 及 `FieldSymbol` 字段；parameter type、隐式 conversion 和
  canonical aggregate shape 不建立伪记录。

宏对象不加密。宏实参/正文中的物理 token 只有在 PySlang 唯一绑定时才作为 selected symbol occurrence；
冲突对象保留并报告 `macro_origin_conflict`。同一 semantic record 重复发现同一物理 range 时在 RenameIndex
收集阶段去重；不同 semantic record 共享 range 时，只有带 PySlang 宏 provenance 的 claim 才按对象报告宏冲突
并移除共享 occurrence。其他跨 record claim 不猜 owner，而是移除冲突 occurrence、将受影响核心组整体 preserve，
并在 `category_outcomes.issues` 中记录物理 `file/start/end`。

## 已有服务器事实

此前 StCache `signals` 已有 `PASS_FULL` 证据：rename 3183，preserve 0，unsupported 0，strict compile
和 byte-identical restore 通过。`ports` 已有 `PASS_PARTIAL`：rename 2636，preserve 587，unsupported 18；
保留原因包括 `outside_top_closure`、`selected_top_boundary` 和已记录的 `macro_origin_conflict`。

这些是历史结果，不代表 T108 重构后的服务器门禁已经通过。T108 的 server gate 必须使用新的输出目录和
`--category all` 重新运行。

## T108 compact 证据

`tests/fixtures/t108_pyslang_rename_index/design.f` 覆盖 interface type、scalar/array instance root、
members、modport、struct type/fields、module signals/ports、top boundary、直接 semantic occurrence、宏实参/正文
唯一来源与冲突、同名 typedef、parameter type、implicit conversion、未知跨 record claim 的组级 preserve、
schema 2、strict gate 和 byte-identical restore。Modport member 不再建立独立 record；struct member 使用
PySlang `FieldSymbol` 的 source location 绑定。mapping 仍严格拒绝重复、重叠或越界 range，不在 validator 中盲目
去重。

`formal.f` 是 Yosys 可读取的 compact cone，用于实际 renamed-gate Formal 正例和固定功能负例。interface
语法本身由 PySlang strict compile、物理 range 审计和 source-free restore 证明；不把 Yosys 不支持的 interface
语法伪装成完整 Formal 证明。

## 验收要求

mapping 使用 `format=rtl-obfuscation.mapping`、`schema_version=2`，四组按固定顺序输出
`category_outcomes`。失败时不得发布半成品 gate；恢复端拒绝 schema 1。

服务器最终命令：

```sh
python rtl_encrypt.py \
  --filelist "$PROJ/aic_ss/src/stcache/StCache.f" \
  --top StChCore \
  --category all \
  --include-dir "$PROJ/common/src/StLib/common" \
  --include-dir "$PROJ/common/src/StLib/impl_template/tsmc4" \
  --output-dir "$OUT"
```

要求无 `REFUSED_ATOMIC`，strict compile 和 byte-identical restore 为 true，四组有可解释的
rename/preserve/unsupported；除既有 top/outside/macro 边界外，不得新增未解释原因。
