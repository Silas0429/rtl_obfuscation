# `project-root + top` Parameter 支持实现计划（草案）

- 文档状态：`DRAFT`
- 前置任务：T030 `ACCEPTED`
- 目标：在保持 top ABI、严格审计和 mapping v3 兼容性的前提下，为 `project-root + top` 增加 module value parameter/localparam 支持。

## 1. 目标输入

需要覆盖以下常见形式：

```systemverilog
module v_int_alu #(
    parameter int DATA_WIDTH = 32,
    parameter int MICROOP_WIDTH = 5,
    parameter int VECTOR_LANES = 8
);
    localparam int PARTIAL_SUM_W = DATA_WIDTH + 8;
    localparam int DIV_BIT_GROUPS = DATA_WIDTH / 4;
    logic [DATA_WIDTH-1:0] data_a_u_ex1;
endmodule
```

第一阶段要支持参数在以下位置的语义引用：

- 普通 constant expression、localparam RHS、procedural loop；
- signal/port dimension；
- generate-for 和 generate-if；
- struct field dimension；
- interface member dimension；
- module named parameter override；
- interface instance override 中对 module parameter 的 RHS 引用。

## 2. 语义边界

### 支持

- module-scoped value parameter；
- module-scoped `localparam`；
- reachable 非 top module 的 parameter/localparam：`eligible`；
- top module value parameter：`preserved(reason="top_parameter")`，保护外部 override ABI；
- top module localparam：可以 `eligible`；
- macro 生成且无法定位到物理 identifier 的对象：`preserved(reason="macro_expansion")`。

### 不支持且必须 fail-closed

- type parameter；
- package/class/interface parameter declaration；
- `$unit` parameter；
- parameter array、string、real 等复杂参数；
- `defparam`、复杂 hierarchical reference；
- 无法确定 owner 的复杂 shadowing；
- struct 作为 parameter 类型。

不得按文本名称全局替换；所有 declaration/reference 必须由 PySlang symbol identity 绑定，并通过源文件 bytes 校验。

对于：

```systemverilog
child #(.WIDTH(DATA_WIDTH)) u_child (...);
```

`.WIDTH` 左侧和 `DATA_WIDTH` RHS 是两个独立 symbol occurrence；positional override 没有参数名左侧 occurrence，但其 RHS 若有语义绑定仍需收集。

## 3. 分阶段路线

### T031：inventory 与 source-range oracle

只读分析，不改写 RTL：

1. 增加显式 `parameters` group；
2. 按 selected-top reachable module 过滤 parameter/localparam；
3. 收集普通表达式、dimension、generate、struct/interface、named override ranges；
4. 验证 top parameter、macro、unreachable module、shadowing 和 unsupported 边界；
5. 固定 compact fixture、range digest 和机器可读 oracle。

Formal verification：`N/A`，因为不产生 rewritten RTL。

### T032：rewrite 闭环

在 T031 fixture 上接通：

1. `--category parameters`；
2. mapping v3 eligible/preserved；
3. gate strict reanalysis、manifest、per-file mapping、metrics；
4. decrypt-project 和逐文件 byte-identical；
5. PySlang、Verible、Icarus、Yosys formal 正负例。

mapping 继续使用 v3，不因增加 parameter category 直接升级 schema。

### T033：RISC-V-Vector 集成

以 `vector_top` 为 top，冻结 `v_int_alu` 的 10 个 parameter + 3 个 localparam，以及普通表达式、generate-if、dimension、struct/interface override 的引用 oracle；验证 19-file closure、mapping、formal-view/formal-align 和正负例 formal。

### T034：默认 profile 晋级（条件任务）

T031/T032 先只支持：

```sh
--category parameters
```

只有 T033 全部通过后，才另开任务将 `parameters` 纳入默认 profile，并重新冻结 FIFO/RISC 默认 oracle。T031/T032 不得改变当前五组默认 profile。

## 4. 代码改造点

### inventory

- `_collect_parameters`：按 reachable module 过滤，排除 type parameter；
- `build_top_project_inventory`：增加 parameter candidate、top preservation、macro preservation；
- `_top_project_references`：增加普通 parameter NamedValue 引用；
- 扩展 `_parameter_dimension_reference_tokens`：覆盖 declaration、port/signal、struct field、interface member dimensions；
- 新增 generate-if/conditional expression collector；
- 扩展 `_named_parameter_override_reference_tokens`，分别处理左侧参数名和 RHS；
- 所有 range 继续做 source bytes、duplicate、overlap 审计。

### project/rewrite

- `_GROUPS` 增加 `parameters: ("parameters",)`；
- `inspect-project`、`encrypt-project --project-root` 接受 `--category parameters`；
- canonical 顺序和重复 category 处理保持确定性；
- mapping v3、gate audit、decrypt、per-file mapping 复用现有通路；
- 默认 profile 暂不变化。

## 5. 测试和验收矩阵

| 阶段 | 必须证明 | Formal |
| --- | --- | --- |
| T031 | inventory、scope、reason、range、determinism、unsupported fail-closed | N/A |
| T032 | encrypt、strict gate、mapping、metrics、decrypt、byte identity | 正例 PASS；功能负例 FAIL |
| T033 | RISC closure、`v_int_alu` oracle、formal-view 对称性 | 正例 PASS；功能负例 FAIL |
| T034 | 默认 profile 数字和文档同步 | 复用 T033 |

所有 Python、parser、HDL、test 和 Yosys 命令必须使用：

```sh
conda run -n rtl_obfuscation ...
```

## 6. 风险与停止条件

- semantic node 没有 syntax token 时，只能在 symbol identity 确认后使用 source-range fallback，并回读 bytes；
- generate-if、packed aggregate、interface override 不暴露统一 AST 字段时，先做最小 API probe，禁止文本扫描补救；
- package/class/compilation-unit 参数超出本阶段 scope，应记录偏差并停止；
- Yosys 不支持的 struct/interface 语法必须使用现有对称 formal-view，不能用 identity formal 冒充；
- 需要修改 fixture、放宽诊断、改变旧 oracle 或扩大语言边界时，子 Agent 必须暂停等待主 Agent。

## 7. 草案结论

方案可行，但不能只把 `parameters` 加入 CLI。关键工作是完整建立 localparam expression、generate-if、struct/interface dimension 和 named override 的语义引用 oracle。建议严格按 T031 → T032 → T033 → 条件性 T034 增量推进。
